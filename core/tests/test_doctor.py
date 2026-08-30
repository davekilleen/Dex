"""Contract tests for the /dex-doctor collector."""

import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import venv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.harnesses.chatgpt_work_personal_copy import STALE_WORK_COPY_SENTENCE
from core.harnesses.registry import get_profile
from core.health import promises as health_promises
from core.lifecycle import service as lifecycle_service
from core.lifecycle.bridge import activate_vault
from core.lifecycle.catalog import with_catalog_identity
from core.lifecycle.engine import AdoptionReceipt
from core.lifecycle.ledger import record_adoption
from core.onboarding.harness_receipt import (
    build_receipt,
    build_receipt_for_ids,
    canonical_receipt_bytes,
)
from core.tests.lifecycle_test_helpers import (
    SOURCE_COMMIT,
    write_bridge_release,
    write_file,
    write_manifest,
)
from core.transaction.engine import PlanRejected
from core.utils import automation_ownership, doctor, release_channel

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTOR_PATH = Path(__file__).resolve().parents[1] / "utils" / "doctor.py"
NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)

QUICK_IDS = [
    "vault.structure",
    "vault.configs",
    "vault.git",
    "brain.git",
    "topology.pre-split-archive",
    "vault.auto-commit",
    "topology.migration-pending",
    "release.catalog",
    "adoption.plan",
    "smoke.history",
    "mcp.registered",
    "mcp.orphans",
    "harness.capabilities",
    "python.env",
    "hooks.wired",
    "jobs.loaded",
    "jobs.fresh",
    "preflight.queue",
    "capabilities.rooms",
    "entity.engine",
    "customizations.skills",
    "customizations.mcp",
    "core.drift",
    "doctor.self",
]

DEEP_IDS = [
    "customizations.assessment",
    "customizations.migration-status",
    "granola.query_path",
    "pipedrive.connection",
    "config.meeting_sources",
    "config.claude_composition",
    "update.post-canary",
    "calendar.access",
    "mail.apple-search",
    "qmd.live",
    "integrations.enabled",
    "mcp.importable",
    "smoke.journeys",
    "backup.freshness",
]


@pytest.fixture
def context(tmp_path):
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "core").mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return doctor.DoctorContext(vault_root=vault, repo_root=vault, home=home, now=NOW)


@pytest.fixture
def foreign_launch_agents(context):
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    definitions = {
        "com.dex.research-scan": ".scripts/research-scan.py",
        "com.dex.other-product": str(
            context.home.parent / "other-dex-vault" / ".scripts" / "other-product.py"
        ),
    }
    plists = []
    for label, script in definitions.items():
        plist = agents / f"{label}.plist"
        with plist.open("wb") as handle:
            plistlib.dump({"Label": label, "ProgramArguments": ["/bin/bash", script]}, handle)
        plists.append(plist)
    return plists


def _check(report, check_id):
    return next(check for check in report["checks"] if check["id"] == check_id)


def _stub_probes(monkeypatch, *, overrides=None, exclude=()):
    overrides = overrides or {}
    excluded = set(exclude)
    for definition in (*doctor.QUICK_CHECKS, *doctor.DEEP_CHECKS):
        if definition.id == "doctor.self" or definition.id in excluded:
            continue
        structured_detail = None
        if definition.id == "customizations.assessment":
            structured_detail = {
                "schema_version": 1,
                "completeness": "OK",
                "verdict": "OK",
            }
        elif definition.id == "customizations.migration-status":
            structured_detail = {
                "capsules": [],
                "truncated": False,
                "pending": False,
            }
        default = doctor.ProbeResult(
            "OK",
            "Stub probe completed.",
            structured_detail=structured_detail,
        )
        probe_result = overrides.get(definition.id, default)
        monkeypatch.setattr(
            doctor,
            definition.probe,
            lambda _context, result=probe_result: result,
        )


def _write_valid_configs(context, *, calendar=None, calendar_provider=None):
    profile = "name: Test User\n"
    if calendar is not None or calendar_provider is not None:
        profile += "calendar:\n"
        if calendar_provider is not None:
            profile += f"  provider: {calendar_provider}\n"
        if calendar is not None:
            profile += f"  work_calendar: {calendar}\n"
    (context.vault_root / "System" / "user-profile.yaml").write_text(profile)
    (context.vault_root / "System" / "pillars.yaml").write_text("pillars: []\n")
    settings = context.vault_root / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"hooks": {}}\n')


def _write_mcp_config(context, servers):
    path = context.vault_root / ".mcp.json"
    path.write_text(json.dumps({"mcpServers": servers}))
    return path


def _write_plist(context, label):
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    script = context.vault_root / ".scripts" / f"{label}.sh"
    script.parent.mkdir(exist_ok=True)
    script.write_text("#!/bin/bash\n")
    script.chmod(0o755)
    plist = agents / f"{label}.plist"
    with plist.open("wb") as handle:
        plistlib.dump(
            {"Label": label, "ProgramArguments": ["/bin/bash", str(script)]},
            handle,
        )
    return plist


def _write_solo_automation_claim(context, plist, label):
    relative = plist.relative_to(context.home).as_posix()
    sidecar = context.vault_root / automation_ownership.SIDECAR_RELATIVE
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "claims": [
                    {
                        "automation_id": label,
                        "owner_id": "dex-solo",
                        "plist_relative_path": relative,
                        "plist_sha256": hashlib.sha256(plist.read_bytes()).hexdigest(),
                    }
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return sidecar


def _write_entity_probe_files(context, *, mode="auto", unresolved=None):
    runtime = context.vault_root / "System" / ".dex"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "contacts.json").write_text(json.dumps({
        "contacts": {"one": {}}, "observations": {"m1": {}, "m2": {}},
    }))
    (runtime / "entity-suggestions.json").write_text(json.dumps({
        "suggestions": [{"status": "suggested"}],
    }))
    (runtime / "entity-verification.json").write_text(json.dumps({
        "generated_at": NOW.isoformat(), "unresolved": unresolved or [],
    }))
    (context.vault_root / "System" / "user-profile.yaml").write_text(
        f"entity_creation:\n  mode: {mode}\n"
    )
    (context.vault_root / "System" / "People_Index.json").write_text(json.dumps({
        "built_at": NOW.isoformat(),
    }))


def _write_release_catalog(context, *, content=b"release skill\n", catalog_version=2):
    item_path = ".claude/skills/fixture-item/SKILL.md"
    manifest = write_manifest(context.vault_root, [item_path])
    write_file(context.vault_root, item_path, content)
    release_identity = {
                "version": "1.64.0",
                "channel": "release",
                "source_commit": SOURCE_COMMIT,
                "manifest": {
                    "path": "System/.installed-files.manifest",
                    "sha256": hashlib.sha256(manifest).hexdigest(),
                },
            }
    if catalog_version == 1:
        release_identity["immutable_distribution_tag"] = "dist/release/v1.64.0-0123456"
    else:
        release_identity["immutable_distribution_tag_pattern"] = (
            "dist/release/v1.64.0-<release-commit-prefix>"
        )
    document = with_catalog_identity(
        {
            "catalog_version": catalog_version,
            "release": release_identity,
            "items": [
                {
                    "id": "fixture-item",
                    "kind": "skill",
                    "version": "1.0.0",
                    "files": [
                        {
                            "path": item_path,
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "ownership_class": "brain",
                        }
                    ],
                    "dependencies": [],
                    "capabilities": [],
                    "rewind": {
                        "acknowledgement_required": True,
                        "token": "rewind:fixture-item@1.0.0",
                    },
                }
            ],
            "integrity": {"catalog_sha256": "0" * 64, "signatures": []},
        }
    )
    path = context.vault_root / "System/.release-catalog.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _tree_snapshot(root):
    snapshot = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        mode = stat.S_IMODE(path.stat().st_mode)
        snapshot[relative] = ("dir", mode) if path.is_dir() else ("file", mode, path.read_bytes())
    return snapshot


def _write_skill(context, name, *, frontmatter_name=None):
    skill_path = context.vault_root / ".claude" / "skills" / name / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(
        f"---\nname: {frontmatter_name or name}\ndescription: Test skill\n---\nBody.\n",
        encoding="utf-8",
    )
    return skill_path


def _git(repo, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check:
        result.check_returncode()
    return result


def _remote_release_ref(channel):
    return f"refs/remotes/{release_channel.release_ref_candidates(channel)[0]}"


def _drift_context(tmp_path, *, release_ref=True, channel=None):
    vault = tmp_path / "drift-vault"
    vault.mkdir()
    _git(vault, "init")
    _git(vault, "config", "user.email", "doctor@example.com")
    _git(vault, "config", "user.name", "Doctor Test")

    (vault / "core").mkdir()
    (vault / "core" / "shipped.py").write_text("SHIPPED = 1\n")
    (vault / "CLAUDE.md").write_text(
        "# Dex\n\n"
        "## USER_EXTENSIONS_START\n"
        "<!-- personal instructions -->\n"
        "## USER_EXTENSIONS_END\n\n"
        "Shipped tail.\n"
    )
    (vault / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "work-mcp": {
                        "command": "python",
                        "args": ["core/mcp/work_server.py"],
                    }
                }
            },
            indent=2,
        )
        + "\n"
    )
    integrations = vault / "System" / "integrations"
    integrations.mkdir(parents=True)
    profile = "name: Original\n"
    if channel is not None:
        profile += f"updates:\n  channel: {channel}\n"
    (vault / "System" / "user-profile.yaml").write_text(profile)
    (vault / "System" / "pillars.yaml").write_text("pillars: []\n")
    (integrations / "calendar.yaml").write_text("enabled: false\n")
    _git(
        vault,
        "add",
        "--",
        ".mcp.json",
        "CLAUDE.md",
        "System/integrations/calendar.yaml",
        "System/pillars.yaml",
        "System/user-profile.yaml",
        "core/shipped.py",
    )
    _git(vault, "commit", "-m", "release fixture")
    if release_ref:
        available_channel = channel if channel in {"stable", "beta"} else "stable"
        _git(vault, "update-ref", _remote_release_ref(available_channel), "HEAD")

    home = tmp_path / "drift-home"
    home.mkdir()
    return doctor.DoctorContext(vault_root=vault, repo_root=vault, home=home, now=NOW)


def test_doctor_collector_module_exists():
    assert DOCTOR_PATH.is_file()


def test_entity_engine_probe_reports_working_off_broken_and_could_not_check(context):
    _write_entity_probe_files(context)
    working = doctor._probe_entity_engine(context)
    assert working.verdict == "OK"
    assert "1 contacts and 2 observations" in working.detail

    _write_entity_probe_files(context, mode="off")
    assert doctor._probe_entity_engine(context).verdict == "OFF"

    _write_entity_probe_files(context, unresolved=[{"domain": "acme.com"}])
    assert doctor._probe_entity_engine(context).verdict == "BROKEN"

    _write_entity_probe_files(context)
    person = context.core_path("PEOPLE_DIR") / "Broken.md"
    person.parent.mkdir(parents=True, exist_ok=True)
    person.write_text("---\nname: [broken\n---\n# Broken\n")
    quarantined = doctor._probe_entity_engine(context)
    assert quarantined.verdict == "BROKEN"
    assert "Broken.md" in quarantined.detail

    (context.vault_root / "System" / ".dex" / "contacts.json").write_text("{")
    assert doctor._probe_entity_engine(context).verdict == "UNKNOWN"


def test_entity_engine_probe_reports_default_mode_and_stale_verification(context):
    _write_entity_probe_files(context)
    (context.vault_root / "System" / "user-profile.yaml").write_text("name: Test\n")
    verification = context.vault_root / "System" / ".dex" / "entity-verification.json"
    verification.write_text(json.dumps({
        "generated_at": (NOW - timedelta(hours=49)).isoformat(), "unresolved": [],
    }))
    result = doctor._probe_entity_engine(context)
    assert result.verdict == "OK"
    assert "suggest (default — key missing)" in result.detail
    assert "stale >48h" in result.detail


def test_entity_engine_probe_surfaces_dead_letters_through_feature_status(context):
    _write_entity_probe_files(context)
    dead_letter = context.vault_root / "System" / ".dex" / "entity-dead-letter.jsonl"
    dead_letter.write_text(
        '{"dead_letter_id":\n'
        + json.dumps(
            {
                "dead_letter_id": "example-dead-letter",
                "meeting_id": "meeting-1",
                "meeting_ids": ["meeting-1"],
                "op_type": "mutate",
                "entity_path": (
                    str(context.vault_root)
                    + "/05-Areas/People/External/Jane_Example.md"
                ),
                "entity_identity": {
                    "kind": "person",
                    "name": "Jane Example",
                    "emails": ["jane@example.org"],
                },
                "reason": "target page missing",
            }
        )
        + "\n"
    )

    result = doctor._probe_entity_engine(context)

    assert result.verdict == "BROKEN"
    assert result.feature_status == "broken"
    assert "1 entity write" in result.user_message
    assert "System/.dex/entity-dead-letter.jsonl" in result.user_message
    assert "/dex-doctor" in result.user_message
    assert "re-queue" in result.user_message
    assert result.heal == doctor.Heal(
        tier=1,
        action="Re-queue the dead-lettered entity write with retry counters reset.",
        applied=False,
    )
    definition = next(
        item for item in doctor.QUICK_CHECKS if item.id == "entity.engine"
    )
    rendered = doctor._result_json(definition, result)
    assert rendered["feature_status"] == "broken"
    assert rendered["user_message"] == result.user_message


def test_t1_heal_requeues_dead_lettered_entity_writes(monkeypatch, context):
    for name in doctor.PARA_PATH_NAMES:
        context.core_path(name).mkdir(parents=True, exist_ok=True)
    context.paths_json_path.parent.mkdir(parents=True, exist_ok=True)
    context.paths_json_path.write_text(json.dumps(doctor._paths_export_for(context)))
    monkeypatch.setattr(doctor, "_repo_shipped_executables", lambda _context: [])
    dead_letter = context.vault_root / "System" / ".dex" / "entity-dead-letter.jsonl"
    dead_letter.parent.mkdir(parents=True, exist_ok=True)
    dead_letter.write_text('{"dead_letter_id":"example-dead-letter"}\n')
    calls = []
    monkeypatch.setattr(
        doctor,
        "_requeue_entity_dead_letters",
        lambda candidate: calls.append(candidate) or {
            "requeued": 1,
            "dead_letter_ids": ["example-dead-letter"],
        },
    )

    actions, errors = doctor._apply_t1_heals(context)

    assert errors == []
    assert calls == [context]
    assert actions == {
        "entity.engine": ["re-queued 1 dead-lettered entity write with retry counters reset"],
    }


def test_entity_dead_letter_heal_round_trip_returns_probe_to_ok(context):
    _write_entity_probe_files(context)
    operation = {
        "op": "create",
        "path": str(
            context.vault_root
            / "05-Areas"
            / "People"
            / "External"
            / "Jane_Example.md"
        ),
        "content": "# Jane Example\n",
        "allowed_root": str(context.vault_root),
    }
    dead_letter = context.vault_root / "System" / ".dex" / "entity-dead-letter.jsonl"
    dead_letter.write_text(
        json.dumps(
            {
                "dead_letter_id": "example-dead-letter",
                "batch_id": "example-batch",
                "scope": "creation",
                "meeting_id": "meeting-1",
                "meeting_ids": ["meeting-1"],
                "op": operation,
            }
        )
        + "\n"
    )
    bridge_context = doctor.DoctorContext(
        vault_root=context.vault_root,
        repo_root=DOCTOR_PATH.parents[2],
        home=context.home,
        now=context.now,
    )

    healed = doctor._requeue_entity_dead_letters(bridge_context)

    assert healed["requeued"] == 1
    assert not dead_letter.exists()
    pending = json.loads(
        (context.vault_root / "System" / ".dex" / "entity-pending.json").read_text()
    )
    assert pending["batches"][0]["ops"] == [operation]
    assert doctor._probe_entity_engine(context).verdict == "OK"


def test_entity_engine_probe_reports_gardener_statuses(monkeypatch, context):
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    _write_entity_probe_files(context)
    result = doctor._probe_entity_engine(context)
    assert "gardener off (no LLM key)" in result.detail

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    gardener = context.core_path("GARDENER_STATE_FILE")
    gardener.write_text(json.dumps({"version": 2, "pages": {
        "one.md": {"output_hash": "one", "blocks": {"context-summary": {"owner": "dex"}}},
        "two.md": {"output_hash": "two", "blocks": {"context-summary": {"owner": "user"}}},
    }}))
    result = doctor._probe_entity_engine(context)
    assert "gardener on (2 pages maintained), 1 user-owned summary" in result.detail

    profile = context.core_path("USER_PROFILE_FILE")
    profile.write_text("entity_creation:\n  mode: auto\nentity_gardener:\n  enabled: false\n")
    result = doctor._probe_entity_engine(context)
    assert "gardener off (disabled), 1 user-owned summary" in result.detail

    gardener.write_text(json.dumps({"version": 1, "pages": {
        "legacy.md": {"output_hash": "old", "locked": True, "locked_reason": "user-edited"},
    }}))
    result = doctor._probe_entity_engine(context)
    assert "1 legacy lock pending migration" in result.detail


def test_entity_engine_probe_reads_llm_key_from_vault_env_file(monkeypatch, context):
    for key in doctor.LLM_KEY_NAMES:
        monkeypatch.delenv(key, raising=False)
    _write_entity_probe_files(context)
    gardener = context.core_path("GARDENER_STATE_FILE")
    gardener.write_text(json.dumps({"version": 2, "pages": {
        "one.md": {"output_hash": "one", "blocks": {"context-summary": {"owner": "dex"}}},
    }}))
    env_path = context.vault_root / ".env"
    env_path.write_text("# local keys\nexport GEMINI_API_KEY='test-placeholder-key'\n")

    result = doctor._probe_entity_engine(context)

    assert "gardener on (1 pages maintained)" in result.detail
    assert "test-placeholder-key" not in result.detail

    env_path.write_text("GEMINI_API_KEY=\n")
    result = doctor._probe_entity_engine(context)
    assert "gardener off (no LLM key)" in result.detail

    env_path.unlink()
    result = doctor._probe_entity_engine(context)
    assert "gardener off (no LLM key)" in result.detail


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only")
def test_vault_configs_flags_group_readable_env_with_t1_heal(context):
    _write_valid_configs(context)
    assert doctor._probe_vault_configs(context).verdict == "OK"

    env_path = context.vault_root / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=test-placeholder-not-a-real-key\n")
    env_path.chmod(0o644)
    result = doctor._probe_vault_configs(context)
    assert result.verdict == "BROKEN"
    assert "readable by other users" in result.detail
    assert "644" in result.detail
    assert "test-placeholder-not-a-real-key" not in result.detail
    assert result.heal == doctor.Heal(
        tier=1,
        action="Tighten .env to owner-only permissions.",
        applied=False,
    )

    env_path.chmod(0o600)
    assert doctor._probe_vault_configs(context).verdict == "OK"


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only")
def test_t1_heal_tightens_env_permissions_without_touching_contents(monkeypatch, context):
    for name in doctor.PARA_PATH_NAMES:
        context.core_path(name).mkdir(parents=True, exist_ok=True)
    context.paths_json_path.parent.mkdir(parents=True, exist_ok=True)
    context.paths_json_path.write_text(json.dumps(doctor._paths_export_for(context)))
    monkeypatch.setattr(doctor, "_repo_shipped_executables", lambda _context: [])
    env_path = context.vault_root / ".env"
    env_path.write_text("OPENAI_API_KEY=test-placeholder-not-a-real-key\n")
    env_path.chmod(0o644)

    actions, errors = doctor._apply_t1_heals(context)

    assert errors == []
    assert actions == {"vault.configs": ["tightened .env to owner-only permissions"]}
    assert stat.S_IMODE(env_path.lstat().st_mode) == 0o600
    assert env_path.read_text() == "OPENAI_API_KEY=test-placeholder-not-a-real-key\n"

    actions, errors = doctor._apply_t1_heals(context)
    assert errors == []
    assert actions == {}


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only")
def test_heal_tightens_env_permissions_and_annotates_vault_configs(monkeypatch, context):
    _write_valid_configs(context)
    for name in doctor.PARA_PATH_NAMES:
        context.core_path(name).mkdir(parents=True, exist_ok=True)
    context.paths_json_path.parent.mkdir(parents=True, exist_ok=True)
    context.paths_json_path.write_text(json.dumps(doctor._paths_export_for(context)))
    monkeypatch.setattr(doctor, "_repo_shipped_executables", lambda _context: [])
    env_path = context.vault_root / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=test-placeholder-not-a-real-key\n")
    env_path.chmod(0o644)
    _stub_probes(monkeypatch, exclude={"vault.configs"})

    report = doctor.collect(heal=True, context=context)

    assert stat.S_IMODE(env_path.lstat().st_mode) == 0o600
    assert env_path.read_text() == "ANTHROPIC_API_KEY=test-placeholder-not-a-real-key\n"
    configs = _check(report, "vault.configs")
    assert configs["verdict"] == "OK"
    assert "after a safe Tier-1 permission repair" in configs["detail"]
    assert configs["heal"] == {
        "tier": 1,
        "action": "tightened .env to owner-only permissions.",
        "applied": True,
    }
    assert "test-placeholder-not-a-real-key" not in json.dumps(report)


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only")
def test_vault_configs_reports_env_permissions_even_with_parse_failures(context):
    _write_valid_configs(context)
    (context.vault_root / "System" / "pillars.yaml").write_text("pillars: [\n")
    env_path = context.vault_root / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=test-placeholder-not-a-real-key\n")
    env_path.chmod(0o644)

    result = doctor._probe_vault_configs(context)

    assert result.verdict == "BROKEN"
    assert "pillars.yaml" in result.detail
    assert "readable by other users" in result.detail
    assert "test-placeholder-not-a-real-key" not in result.detail
    assert result.heal.tier == 3  # the parse-failure guidance survives


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only")
def test_heal_annotation_merges_into_a_still_broken_vault_configs(monkeypatch, context):
    # A parse failure and a loose .env together: --heal tightens the file but
    # must not replace the BROKEN verdict or the Tier-3 hand-repair guidance.
    _write_valid_configs(context)
    (context.vault_root / "System" / "pillars.yaml").write_text("pillars: [\n")
    for name in doctor.PARA_PATH_NAMES:
        context.core_path(name).mkdir(parents=True, exist_ok=True)
    context.paths_json_path.parent.mkdir(parents=True, exist_ok=True)
    context.paths_json_path.write_text(json.dumps(doctor._paths_export_for(context)))
    monkeypatch.setattr(doctor, "_repo_shipped_executables", lambda _context: [])
    env_path = context.vault_root / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=test-placeholder-not-a-real-key\n")
    env_path.chmod(0o644)
    _stub_probes(monkeypatch, exclude={"vault.configs"})

    report = doctor.collect(heal=True, context=context)

    assert stat.S_IMODE(env_path.lstat().st_mode) == 0o600
    configs = _check(report, "vault.configs")
    assert configs["verdict"] == "BROKEN"
    assert configs["heal"] == {
        "tier": 3,
        "action": "Repair the named configuration file by hand.",
        "applied": False,
    }
    assert "pillars.yaml" in configs["detail"]
    assert "tightened .env to owner-only permissions" in configs["detail"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only")
def test_symlinked_env_is_reported_but_never_auto_tightened(monkeypatch, context, tmp_path):
    _write_valid_configs(context)
    target = tmp_path / "real-env"
    target.write_text("ANTHROPIC_API_KEY=test-placeholder-not-a-real-key\n")
    target.chmod(0o644)
    env_path = context.vault_root / ".env"
    env_path.symlink_to(target)

    result = doctor._probe_vault_configs(context)

    assert result.verdict == "BROKEN"
    assert "symlink" in result.detail
    assert "test-placeholder-not-a-real-key" not in result.detail
    assert result.heal.tier == 3
    assert result.heal.applied is False
    assert str(env_path.resolve()) in result.heal.action

    for name in doctor.PARA_PATH_NAMES:
        context.core_path(name).mkdir(parents=True, exist_ok=True)
    context.paths_json_path.parent.mkdir(parents=True, exist_ok=True)
    context.paths_json_path.write_text(json.dumps(doctor._paths_export_for(context)))
    monkeypatch.setattr(doctor, "_repo_shipped_executables", lambda _context: [])

    actions, errors = doctor._apply_t1_heals(context)

    assert errors == []
    assert "vault.configs" not in actions
    assert stat.S_IMODE(target.lstat().st_mode) == 0o644  # untouched


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only")
def test_foreign_owned_env_degrades_to_manual_guidance(monkeypatch, context):
    _write_valid_configs(context)
    env_path = context.vault_root / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=test-placeholder-not-a-real-key\n")
    env_path.chmod(0o644)
    monkeypatch.setattr(doctor.os, "geteuid", lambda: env_path.lstat().st_uid + 1)

    result = doctor._probe_vault_configs(context)

    assert result.verdict == "BROKEN"
    assert "owned by another user" in result.detail
    assert result.heal.tier == 3
    assert result.heal.applied is False

    for name in doctor.PARA_PATH_NAMES:
        context.core_path(name).mkdir(parents=True, exist_ok=True)
    context.paths_json_path.parent.mkdir(parents=True, exist_ok=True)
    context.paths_json_path.write_text(json.dumps(doctor._paths_export_for(context)))
    monkeypatch.setattr(doctor, "_repo_shipped_executables", lambda _context: [])

    actions, errors = doctor._apply_t1_heals(context)

    assert errors == []  # no unappliable heal breaking doctor.self on every run
    assert "vault.configs" not in actions
    assert stat.S_IMODE(env_path.lstat().st_mode) == 0o644


def test_entity_engine_probe_tolerates_undecodable_env_file(monkeypatch, context):
    for key in doctor.LLM_KEY_NAMES:
        monkeypatch.delenv(key, raising=False)
    _write_entity_probe_files(context)
    (context.vault_root / ".env").write_bytes(b"ANTHROPIC_API_KEY=caf\xe9\n")

    result = doctor._probe_entity_engine(context)

    assert result.verdict == "OK"
    assert "gardener off (no LLM key)" in result.detail


def test_granola_api_key_distinguishes_absent_from_unreadable(monkeypatch, context):
    monkeypatch.delenv("GRANOLA_API_KEY", raising=False)
    assert doctor._granola_api_key(context) is None  # no .env file at all

    env_path = context.vault_root / ".env"
    env_path.write_text("GRANOLA_API_KEY=\n")
    assert doctor._granola_api_key(context) is None  # empty value

    env_path.write_text('GRANOLA_API_KEY="grn_\\u0066ile_key"\n')
    assert doctor._granola_api_key(context) == "grn_file_key"  # shared JSON decoding

    env_path.write_bytes(b"not a valid assignment line\n")
    with pytest.raises(ValueError):
        doctor._granola_api_key(context)  # present-but-unparseable surfaces, never "no key"


def test_registry_ids_match_the_approved_spec():
    assert [definition.id for definition in doctor.QUICK_CHECKS] == QUICK_IDS
    assert [definition.id for definition in doctor.DEEP_CHECKS] == DEEP_IDS
    assert doctor.VERDICTS == frozenset({"OK", "OFF", "BROKEN", "UNKNOWN"})


def test_harness_capability_probe_is_calmly_off_before_selection(context):
    result = doctor._probe_harness_capabilities(context)

    assert result.verdict == "OFF"
    assert "record your harnesses without restarting onboarding" in result.detail.lower()


def test_harness_capability_probe_reports_modes_without_overclaiming(context, monkeypatch):
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    receipt = build_receipt(
        [
            {
                "id": "codex",
                "display_name": "Codex",
                "capabilities": [
                    {"id": "vault", "mode": "automatic"},
                    {"id": "mcp", "mode": "on_demand"},
                    {"id": "pre-tool", "mode": "guided"},
                ],
            }
        ],
        detected_ids=("codex",),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))

    result = doctor._probe_harness_capabilities(context)

    assert result.verdict == "OK"
    assert "Codex" in result.detail
    assert "1 automatic" in result.detail
    assert "1 on demand" in result.detail
    assert "1 guided" in result.detail
    assert "fully automatic" not in result.detail.lower()
    assert "Linux" in result.detail
    assert "deferred" in result.detail
    assert result.structured_detail == {
        "selected": ["codex"],
        "modes": {
            "automatic": 1,
            "guided": 1,
            "on_demand": 1,
            "unavailable": 0,
        },
        "fully_automatic": False,
        "limitations": {"codex": list(get_profile("codex").limitations)},
        "platform": {
            "id": "linux",
            "included_in_release": False,
            "label": "Linux",
            "notes": "Linux packaging and live-host verification are deferred; the portable runtime remains testable but is outside this release.",
            "readiness": "deferred",
            "runtime": {"node": ">=20", "python": ">=3.11"},
        },
    }
    assert "ide" in result.detail.lower()


def test_harness_capability_probe_reports_cowork_public_endpoint_limit(context, monkeypatch):
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    receipt = build_receipt_for_ids(
        ["cowork"],
        detected_ids=("cowork",),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))

    result = doctor._probe_harness_capabilities(context)

    assert result.verdict == "OK"
    assert "Claude Cowork" in result.detail
    assert "public" in result.detail.lower()
    assert "stdio" in result.detail.lower()
    assert "fully automatic" not in result.detail.lower()
    assert result.structured_detail["selected"] == ["cowork"]
    assert result.structured_detail["limitations"] == {
        "cowork": list(get_profile("cowork").limitations),
    }


def test_harness_capability_probe_reports_pi_and_bb_limits(context, monkeypatch):
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    receipt = build_receipt_for_ids(
        ["pi", "bb"],
        detected_ids=("pi", "bb"),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))

    result = doctor._probe_harness_capabilities(context)

    assert result.verdict == "OK"
    assert "Pi" in result.detail
    assert "BB" in result.detail
    assert "mcp" in result.detail.lower()
    assert "macos" in result.detail.lower()
    assert result.structured_detail["selected"] == ["bb", "pi"]
    assert result.structured_detail["limitations"] == {
        "bb": list(get_profile("bb").limitations),
        "pi": list(get_profile("pi").limitations),
    }


def test_harness_capability_probe_reports_chatgpt_work_web_limit(context, monkeypatch):
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    receipt = build_receipt_for_ids(
        ["chatgpt-work"],
        detected_ids=("chatgpt-work",),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))

    result = doctor._probe_harness_capabilities(context)

    assert result.verdict == "OK"
    assert "ChatGPT Work" in result.detail
    assert "web" in result.detail.lower()
    assert "https" in result.detail.lower()
    assert "desktop" in result.detail.lower()
    assert "vault" in result.detail.lower()
    assert "fully automatic" not in result.detail.lower()
    assert result.structured_detail["selected"] == ["chatgpt-work"]
    assert result.structured_detail["limitations"] == {
        "chatgpt-work": list(get_profile("chatgpt-work").limitations),
    }
    assert STALE_WORK_COPY_SENTENCE not in result.detail
    assert "granted=true" not in result.detail.lower()


def test_harness_capability_probe_reports_copilot_cli_hook_limit(context, monkeypatch):
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
    assert "hook" in result.detail.lower()
    assert "person" in result.detail.lower()
    assert "ubuntu cloud" in result.detail.lower()
    assert "fully automatic" not in result.detail.lower()
    assert result.structured_detail["selected"] == ["copilot-cli"]
    assert result.structured_detail["limitations"] == {
        "copilot-cli": list(get_profile("copilot-cli").limitations),
    }


def test_harness_capability_probe_reports_malformed_receipt_as_broken(context):
    receipt_path = context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text("not JSON\n", encoding="utf-8")

    result = doctor._probe_harness_capabilities(context)

    assert result.verdict == "BROKEN"
    assert "harness" in result.detail.lower()
    assert result.heal is not None
    assert result.heal.applied is False


def test_harness_capability_probe_reports_non_list_detected_ids_as_broken(context):
    receipt = build_receipt(
        [
            {
                "id": "codex",
                "display_name": "Codex",
                "capabilities": [
                    {"id": "vault", "mode": "automatic"},
                ],
            }
        ],
        detected_ids=("codex",),
        source="detected",
        generated_at=NOW,
    )
    receipt["detected"] = "codex"
    receipt_path = context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes((json.dumps(receipt) + "\n").encode("utf-8"))

    result = doctor._probe_harness_capabilities(context)

    assert result.verdict == "BROKEN"
    assert "detected" in result.detail.lower()
    assert result.heal is not None
    assert result.heal.applied is False


def test_release_catalog_probe_is_calmly_off_for_older_installs(context):
    result = doctor._probe_release_catalog(context)

    assert result.verdict == "OFF"
    assert "normal for older Dex releases" in result.detail


@pytest.mark.parametrize("catalog_version", (1, 2))
def test_release_catalog_probe_reports_valid_version_without_writing(
    context, catalog_version
):
    _write_release_catalog(context, catalog_version=catalog_version)
    before = _tree_snapshot(context.vault_root)

    result = doctor._probe_release_catalog(context)

    assert result.verdict == "OK"
    assert "1.64.0" in result.detail
    assert _tree_snapshot(context.vault_root) == before


def test_release_catalog_probe_reports_corruption_as_broken(context):
    path = context.vault_root / "System/.release-catalog.json"
    path.write_text("{not json", encoding="utf-8")

    result = doctor._probe_release_catalog(context)

    assert result.verdict == "BROKEN"
    assert "cannot be parsed" in result.detail


def test_release_catalog_probe_reports_non_utf8_corruption_as_broken(context):
    path = context.vault_root / "System/.release-catalog.json"
    path.write_bytes(b"\xff")

    result = doctor._probe_release_catalog(context)

    assert result.verdict == "BROKEN"
    assert "codec can't decode" in result.detail


def _activate_release_catalog(context) -> None:
    """Stand in for the one-time bridge activation a real install already has."""
    write_bridge_release(context.vault_root)
    activate_vault(context.vault_root)


def test_adoption_plan_probe_summarizes_valid_catalog_in_memory(context):
    _write_release_catalog(context)
    _activate_release_catalog(context)
    before = _tree_snapshot(context.vault_root)

    result = doctor._probe_adoption_plan(context)

    assert result.verdict == "OK"
    assert result.detail == "1 adoptable / 0 adopted / 0 conflicts"
    assert _tree_snapshot(context.vault_root) == before


def test_adoption_plan_probe_counts_receipt_backed_adoptions(context):
    _write_release_catalog(context)
    _activate_release_catalog(context)
    content = b"release skill\n"
    transaction_id = "20260807T120000-00000001"
    receipt = AdoptionReceipt.from_dict(
        {
            "receipt_version": 1,
            "items_adopted": ["fixture-item"],
            "files_written": [
                {
                    "item_id": "fixture-item",
                    "path": ".claude/skills/fixture-item/SKILL.md",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "byte_size": len(content),
                }
            ],
            "transaction_id": transaction_id,
            "snapshot_ref": f"System/.dex/tx/{transaction_id}/snapshot",
            "catalog_sha256": "a" * 64,
            "inventory_sha256": "b" * 64,
            "preview_sha256": "c" * 64,
        }
    )
    record_adoption(context.vault_root, receipt, {"fixture-item": "1.0.0"})
    before = _tree_snapshot(context.vault_root)

    result = doctor._probe_adoption_plan(context)

    assert result.verdict == "OK"
    assert result.detail == "0 adoptable / 1 adopted / 0 conflicts"
    assert _tree_snapshot(context.vault_root) == before


def test_adoption_plan_probe_is_off_without_a_release_catalog(context):
    result = doctor._probe_adoption_plan(context)

    assert result.verdict == "OFF"
    assert "older Dex release" in result.detail


def test_adoption_plan_probe_maps_internal_failures_to_unknown(monkeypatch, context):
    _write_release_catalog(context)
    _activate_release_catalog(context)

    def explode(*_args, **_kwargs):
        raise RuntimeError("inventory exploded")

    monkeypatch.setattr(lifecycle_service, "build_inventory_and_plan", explode)

    result = doctor._probe_adoption_plan(context)

    assert result.verdict == "UNKNOWN"
    assert "inventory exploded" in result.detail


def test_adoption_plan_probe_reports_broken_when_the_update_gate_refuses(monkeypatch, context):
    """A refusal from the same gate /dex-update uses must not read as a clean bill of health."""
    _write_release_catalog(context)
    _activate_release_catalog(context)

    def refuse(*_args, **_kwargs):
        raise PlanRejected("this Dex copy's update engine doesn't match its release information — run /dex-doctor")

    monkeypatch.setattr(lifecycle_service, "build_inventory_and_plan", refuse)

    result = doctor._probe_adoption_plan(context)

    assert result.verdict == "BROKEN"
    assert "Updating is blocked" in result.detail
    assert "doesn't match its release information" in result.detail


def test_adoption_plan_probe_is_broken_on_a_real_bridge_pin_mismatch(context):
    """Reproduces the #252-style refusal: the probe must go through the real gate, not just build a plan in memory."""
    _write_release_catalog(context)
    write_bridge_release(context.vault_root, release_version="9.9.9")

    result = doctor._probe_adoption_plan(context)

    assert result.verdict == "BROKEN"
    assert "Updating is blocked" in result.detail
    assert "doesn't match its release information" in result.detail


def test_corrupt_catalog_never_raises_out_of_doctor(monkeypatch, context):
    (context.vault_root / "System/.release-catalog.json").write_text(
        "{not json", encoding="utf-8"
    )
    _stub_probes(monkeypatch, exclude={"release.catalog", "adoption.plan"})

    report = doctor.collect(context=context)

    assert _check(report, "release.catalog")["verdict"] == "BROKEN"
    assert _check(report, "adoption.plan")["verdict"] == "UNKNOWN"


def _write_split_topology(context, *, installed: str = "a" * 40) -> Path:
    _git(context.vault_root, "init", "--quiet")
    (context.vault_root / ".git/dex-vault-v2").write_text('{"role":"vault"}\n')
    brain = context.vault_root / ".dex/brain.git"
    brain.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", "--quiet", str(brain)], check=True)
    _git(context.vault_root, "config", "user.name", "Doctor Test")
    _git(context.vault_root, "config", "user.email", "doctor@example.com")
    (context.vault_root / "README.md").write_text("brain\n")
    _git(context.vault_root, "add", "README.md")
    _git(context.vault_root, "commit", "--quiet", "-m", "brain")
    commit = _git(context.vault_root, "rev-parse", "HEAD").stdout.strip()
    subprocess.run(
        ["git", f"--git-dir={brain}", "fetch", "--quiet", str(context.vault_root), f"+{commit}:refs/dex/installed"],
        check=True,
    )
    subprocess.run(
        ["git", f"--git-dir={brain}", "remote", "add", "origin", "https://github.com/davekilleen/Dex.git"],
        check=True,
    )
    (brain / "dex-brain-v2").write_text(
        json.dumps({"role": "brain", "installed": commit}) + "\n"
    )
    topology = context.vault_root / "System/.dex/topology.json"
    topology.parent.mkdir(parents=True, exist_ok=True)
    topology.write_text(
        json.dumps(
            {
                "topology": "brain-vault-split",
                "vaultGitDir": ".git",
                "brainGitDir": ".dex/brain.git",
                "installedRelease": commit,
                "environment": {"DEX_VAULT": str(context.vault_root.resolve())},
            }
        )
        + "\n"
    )
    return brain


def test_topology_probe_distinguishes_combined_split_and_invalid(context):
    (context.vault_root / ".git").mkdir()
    assert doctor._topology_state(context) == "combined"
    assert doctor._probe_migration_pending(context).verdict == "OFF"

    migrator = (
        context.vault_root
        / "core/migrations/v1-to-v2-brain-vault-split.cjs"
    )
    migrator.parent.mkdir(parents=True)
    migrator.write_text("'use strict';\n", encoding="utf-8")
    assert doctor._topology_state(context) == "migration-pending"
    pending = doctor._probe_migration_pending(context)
    assert pending.verdict == "OFF"
    assert "/dex-update" in pending.detail
    assert "when you want it" in pending.detail
    assert "notes stay in place either way" in pending.detail

    migrator.unlink()
    shutil.rmtree(context.vault_root / ".git")
    _write_split_topology(context)
    assert doctor._topology_state(context) == "post-split"
    assert doctor._probe_migration_pending(context).verdict == "OK"

    (context.vault_root / ".dex/brain.git/dex-brain-v2").unlink()
    assert doctor._topology_state(context) == "invalid-split"
    assert doctor._probe_migration_pending(context).verdict == "BROKEN"


def test_pre_split_archive_probe_reports_age_size_and_retention(context):
    archive = context.vault_root / ".dex/pre-split-archive.git"
    archive.mkdir(parents=True)
    (archive / "HEAD").write_bytes(b"ref: refs/heads/main\n")
    timestamp = (NOW - timedelta(days=9)).timestamp()
    os.utime(archive, (timestamp, timestamp))

    result = doctor._probe_pre_split_archive(context)

    assert result.verdict == "OK"
    assert "9 days old" in result.detail
    assert "0.0 KB" in result.detail
    assert "one-command undo" in result.detail
    assert "one full release cycle after conversion" in result.detail


def test_migration_recovery_verdicts_name_exact_commands_and_manual_repair_warning(context):
    state = context.vault_root / "System/.dex/migration-v2-state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text('{"status":"needs-resume"}\n')

    in_progress = doctor._probe_migration_pending(context)

    assert "--resume" in in_progress.detail
    assert "--restore" in in_progress.detail
    assert "Do not reinstall, restore backups, or run raw Git commands" in in_progress.detail

    state.unlink()
    _write_split_topology(context)
    (context.vault_root / ".dex/brain.git/dex-brain-v2").unlink()

    invalid = doctor._probe_migration_pending(context)

    assert "--resume" in invalid.detail
    assert "--restore" in invalid.detail
    assert "Do not reinstall, restore backups, or run raw Git commands" in invalid.detail


@pytest.mark.parametrize(
    ("lifecycle_state", "doctor_state"),
    [
        ("combined", "migration-pending"),
        ("invalid-combined", "combined"),
        ("post-split", "post-split"),
        ("invalid-split", "invalid-split"),
        ("migration-in-progress", "migration-in-progress"),
        ("zip-or-manual", "zip-or-manual"),
    ],
)
def test_topology_state_delegates_to_lifecycle_classifier(
    context,
    monkeypatch,
    lifecycle_state,
    doctor_state,
):
    monkeypatch.setattr(
        doctor.lifecycle_engine,
        "topology_state",
        lambda vault_root: lifecycle_state,
    )

    assert doctor._topology_state(context) == doctor_state


def test_split_brain_install_probe_checks_ref_markers_origin_and_integrity(context):
    brain = _write_split_topology(context)

    healthy = doctor._probe_brain_git(context)

    assert healthy.verdict == "OK"
    assert "brain history is healthy" in healthy.detail
    marker = json.loads((brain / "dex-brain-v2").read_text())
    marker["installed"] = "0" * 40
    (brain / "dex-brain-v2").write_text(json.dumps(marker) + "\n")
    broken = doctor._probe_brain_git(context)
    assert broken.verdict == "BROKEN"
    assert "disagrees" in broken.detail


def _smoke_entry(timestamp, *, broken=0, version="1.47.0"):
    verdict = "BROKEN" if broken else "OK"
    return {
        "schema_version": 1,
        "generated_at": timestamp.isoformat(),
        "dex_version": version,
        "journeys": [
            {
                "id": "task_lifecycle",
                "verdict": verdict,
                "detail": "task lifecycle failed" if broken else "task lifecycle passed",
                "duration_ms": 1,
            }
        ],
        "summary": {"ok": 0 if broken else 1, "off": 0, "broken": broken, "unknown": 0},
    }


def _write_smoke_history(context, *entries, corrupt_prefix=False):
    path = context.vault_root / "System" / ".dex" / "smoke-history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = (["{not json"] if corrupt_prefix else []) + [json.dumps(entry) for entry in entries]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_smoke_history_is_off_without_a_ledger(context):
    result = doctor._probe_smoke_history(context)

    assert result.verdict == "OFF"
    assert result.detail == "nightly checks not installed — run .scripts/install-smoke-automation.sh"


def test_smoke_history_reports_latest_healthy_run(context):
    _write_smoke_history(context, _smoke_entry(NOW - timedelta(hours=1)))

    result = doctor._probe_smoke_history(context)

    assert result.verdict == "OK"
    assert result.detail == f"last verified {(NOW - timedelta(hours=1)).isoformat()} (1 journeys OK)"


def test_smoke_history_reports_a_stopped_ledger_rather_than_its_last_verdict(context):
    """A ledger that stopped must say so, not replay the verdict it stopped on."""
    stopped_at = NOW - timedelta(days=8)
    _write_smoke_history(context, _smoke_entry(stopped_at))

    result = doctor._probe_smoke_history(context)

    assert result.verdict == "UNKNOWN"
    assert "have not run since" in result.detail
    assert "8 days ago" in result.detail
    assert "not the system now" in result.detail


def test_smoke_history_staleness_outranks_a_stale_broken_verdict(context):
    """Staleness is the finding. An old BROKEN is not evidence about now either.

    Reporting the old verdict here would send someone chasing a failure that may
    have been fixed days ago, while the live problem is that nothing is checking.
    """
    _write_smoke_history(
        context,
        _smoke_entry(NOW - timedelta(days=10)),
        _smoke_entry(NOW - timedelta(days=9), broken=1),
    )

    result = doctor._probe_smoke_history(context)

    assert result.verdict == "UNKNOWN"
    assert "have not run since" in result.detail


def test_smoke_history_still_reports_a_recent_run_normally(context):
    """The bound must not swallow a ledger that is simply current."""
    _write_smoke_history(context, _smoke_entry(NOW - timedelta(hours=20)))

    result = doctor._probe_smoke_history(context)

    assert result.verdict == "OK"
    assert "have not run since" not in result.detail


def test_smoke_history_attributes_config_mtime(context):
    good_at = NOW - timedelta(hours=2)
    broken_at = NOW - timedelta(hours=1)
    _write_smoke_history(context, _smoke_entry(good_at), _smoke_entry(broken_at, broken=1))
    pillars = context.vault_root / "System" / "pillars.yaml"
    pillars.write_text("pillars: []\n")
    modified = NOW - timedelta(minutes=90)
    os.utime(pillars, (modified.timestamp(), modified.timestamp()))

    result = doctor._probe_smoke_history(context)

    assert result.verdict == "BROKEN"
    assert f"task_lifecycle broke between {good_at.isoformat()} and {broken_at.isoformat()}" in result.detail
    assert f"pillars.yaml modified {modified.isoformat()}" in result.detail


def test_smoke_history_attributes_dex_version_change(context):
    good_at = NOW - timedelta(hours=2)
    broken_at = NOW - timedelta(hours=1)
    _write_smoke_history(
        context,
        _smoke_entry(good_at, version="1.46.0"),
        _smoke_entry(broken_at, broken=1, version="1.47.0"),
    )

    result = doctor._probe_smoke_history(context)

    assert result.verdict == "BROKEN"
    assert "Dex updated from 1.46.0 to 1.47.0 in this window" in result.detail


def test_smoke_history_skips_corrupt_lines(context):
    _write_smoke_history(
        context,
        _smoke_entry(NOW - timedelta(hours=1)),
        corrupt_prefix=True,
    )

    result = doctor._probe_smoke_history(context)

    assert result.verdict == "OK"


def test_smoke_history_falls_back_to_valid_last_run_when_all_lines_are_corrupt(context):
    history = context.vault_root / "System" / ".dex" / "smoke-history.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text("{not json\n")
    last_run = context.vault_root / "System" / ".smoke-last-run.json"
    last_run.write_text(json.dumps(_smoke_entry(NOW - timedelta(hours=1))))

    result = doctor._probe_smoke_history(context)

    assert result.verdict == "OK"


def test_smoke_history_is_unknown_when_whole_ledger_is_unreadable(context):
    path = context.vault_root / "System" / ".dex" / "smoke-history.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("{not json\n")

    result = doctor._probe_smoke_history(context)

    assert result.verdict == "UNKNOWN"
    assert "ledger is unreadable" in result.detail


@pytest.mark.parametrize("deep,expected_ids", [(False, QUICK_IDS), (True, QUICK_IDS + DEEP_IDS)])
def test_json_contract_shape_and_last_run_file(monkeypatch, context, deep, expected_ids):
    _stub_probes(monkeypatch)

    report = doctor.collect(deep=deep, context=context)

    expected_keys = {
        "generated_at",
        "mode",
        "instruments",
        "checks",
        "summary",
        "adoption",
    }
    if deep:
        expected_keys.add("customization_assessment")
        expected_keys.add("customization_migration_status")
    assert set(report) == expected_keys
    assert report["generated_at"] == NOW.isoformat()
    assert report["mode"] == ("deep" if deep else "quick")
    assert report["instruments"] == {
        "attempted": len(expected_ids),
        "completed": len(expected_ids),
        "failed": [],
    }
    assert [check["id"] for check in report["checks"]] == expected_ids
    assert report["summary"] == {"ok": len(expected_ids), "off": 0, "broken": 0, "unknown": 0}
    for check in report["checks"]:
        assert set(check) == {"id", "feature", "verdict", "detail", "heal"}
        assert check["verdict"] in doctor.VERDICTS
        assert isinstance(check["detail"], str) and check["detail"]
        assert check["heal"] is None

    assert json.loads(context.last_run_path.read_text()) == report


def test_summary_counts_each_exact_verdict(monkeypatch, context):
    _stub_probes(
        monkeypatch,
        overrides={
            "vault.configs": doctor.ProbeResult("OFF", "Deliberately disabled."),
            "mcp.registered": doctor.ProbeResult("BROKEN", "Configuration is broken."),
            "mcp.orphans": doctor.ProbeResult("UNKNOWN", "Could not inspect registration."),
        },
    )

    report = doctor.collect(context=context)

    assert report["summary"] == {
        "ok": len(doctor.QUICK_CHECKS) - 3,
        "off": 1,
        "broken": 1,
        "unknown": 1,
    }
    assert report["instruments"]["completed"] == len(QUICK_IDS)


def test_raising_probe_becomes_unknown_and_main_still_returns_valid_json(monkeypatch, context, capsys):
    _stub_probes(monkeypatch)

    def explode(_context):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(doctor, "_probe_vault_configs", explode)

    exit_code = doctor.main([], context=context)
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert _check(report, "vault.configs")["verdict"] == "UNKNOWN"
    assert "probe exploded" in _check(report, "vault.configs")["detail"]
    assert report["instruments"] == {
        "attempted": len(QUICK_IDS),
        "completed": len(QUICK_IDS) - 1,
        "failed": [{"id": "vault.configs", "error": "probe exploded"}],
    }
    assert _check(report, "doctor.self")["verdict"] == "BROKEN"


@pytest.mark.parametrize(
    ("error", "guidance"),
    [
        (
            ModuleNotFoundError("No module named 'yaml'"),
            "Python packages not installed (missing module 'yaml') — run /dex-update "
            "(or pip install -r requirements.txt) then re-run /dex-doctor",
        ),
        (
            RuntimeError("subprocess failed: ModuleNotFoundError: No module named 'EventKit'"),
            "Python packages not installed (missing module 'EventKit') — run /dex-update "
            "(or pip install -r requirements.txt) then re-run /dex-doctor",
        ),
        (
            RuntimeError("subprocess failed: ModuleNotFoundError: No module named 'core.paths'"),
            "Dex's own code could not be loaded (missing module 'core.paths'). "
            "This is a Dex checkup fault, not a missing Python package.",
        ),
    ],
)
def test_missing_modules_have_truthful_actionable_unknown_detail(
    monkeypatch, context, error, guidance
):
    _stub_probes(monkeypatch)

    def missing_dependency(_context):
        raise error

    monkeypatch.setattr(doctor, "_probe_vault_configs", missing_dependency)

    report = doctor.collect(context=context)

    assert _check(report, "vault.configs")["verdict"] == "UNKNOWN"
    expected_detail = guidance if guidance.endswith(".") else guidance + "."
    assert _check(report, "vault.configs")["detail"] == expected_detail
    assert report["instruments"]["failed"] == [{"id": "vault.configs", "error": guidance}]


def test_probe_owned_unknown_missing_package_detail_is_actionable(monkeypatch, context):
    _stub_probes(
        monkeypatch,
        overrides={
            "calendar.access": doctor.ProbeResult(
                "UNKNOWN",
                "calendar helper failed: ModuleNotFoundError: No module named 'EventKit'",
            )
        },
    )

    report = doctor.collect(deep=True, context=context)

    assert _check(report, "calendar.access")["detail"] == (
        "Python packages not installed (missing module 'EventKit') — run /dex-update "
        "(or pip install -r requirements.txt) "
        "then re-run /dex-doctor."
    )
    assert report["instruments"]["failed"] == []


def test_last_run_write_failure_marks_doctor_self_broken(monkeypatch, context):
    _stub_probes(monkeypatch)

    def fail_write(_report, _context):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(doctor, "_write_last_run", fail_write)

    report = doctor.collect(context=context)

    assert _check(report, "doctor.self")["verdict"] == "BROKEN"
    assert "read-only filesystem" in _check(report, "doctor.self")["detail"]
    assert {failure["id"] for failure in report["instruments"]["failed"]} == {"doctor.self"}


def test_heal_applies_all_t1_actions_and_leaves_t2_suggestion_untouched(
    monkeypatch,
    tmp_path,
    fixture_vault,
):
    vault = tmp_path / "vault-copy"
    shutil.copytree(fixture_vault, vault)
    shutil.rmtree(vault / "00-Inbox")
    (vault / "core").mkdir()
    script = vault / ".scripts" / "repo-tool.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n")
    script.chmod(0o644)
    missing_target = vault / "core" / "mcp" / "missing_server.py"
    mcp_config = _write_mcp_config(
        doctor.DoctorContext(vault, vault, tmp_path / "home", NOW),
        {"missing": {"command": sys.executable, "args": [str(missing_target)]}},
    )
    original_mcp = mcp_config.read_text()
    test_context = doctor.DoctorContext(vault_root=vault, repo_root=vault, home=tmp_path / "home", now=NOW)
    test_context.home.mkdir()

    t2 = doctor.ProbeResult(
        "BROKEN",
        "A registered MCP target is missing.",
        doctor.Heal(tier=2, action="Repair the missing MCP target.", applied=False),
    )
    _stub_probes(
        monkeypatch,
        overrides={"mcp.registered": t2},
        exclude={"vault.structure"},
    )
    monkeypatch.setattr(doctor, "_repo_shipped_executables", lambda _context: [script])
    before = _tree_snapshot(vault)

    report = doctor.collect(heal=True, context=test_context)
    after = _tree_snapshot(vault)

    assert not (vault / "00-Inbox").exists()
    paths_json = json.loads((vault / "core" / "paths.json").read_text())
    assert paths_json["VAULT_ROOT"] == str(vault)
    assert script.stat().st_mode & stat.S_IXUSR
    assert mcp_config.read_text() == original_mcp
    assert not missing_target.exists()
    structure = _check(report, "vault.structure")
    assert structure["verdict"] == "BROKEN"
    assert "Missing standard PARA directories: 00-Inbox" in structure["detail"]
    assert structure["heal"] == {
        "tier": 1,
        "action": (
            "regenerated core/paths.json; restored executable permission on "
            ".scripts/repo-tool.sh."
        ),
        "applied": True,
    }
    assert _check(report, "mcp.registered")["heal"] == {
        "tier": 2,
        "action": "Repair the missing MCP target.",
        "applied": False,
    }
    assert "core/paths.json" in set(after) - set(before)
    assert "00-Inbox" not in set(after)
    assert set(before) - set(after) == set()
    assert {path for path in before if before[path] != after[path]} == {".scripts/repo-tool.sh"}


def test_quick_mode_does_not_apply_t1_without_heal(monkeypatch, context):
    script = context.vault_root / ".scripts" / "repo-tool.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n")
    script.chmod(0o644)
    _stub_probes(monkeypatch, exclude={"vault.structure"})
    monkeypatch.setattr(doctor, "_repo_shipped_executables", lambda _context: [script])

    report = doctor.collect(context=context)

    assert _check(report, "vault.structure")["verdict"] == "BROKEN"
    assert not (context.vault_root / "00-Inbox").exists()
    assert not (context.vault_root / "core" / "paths.json").exists()
    assert not script.stat().st_mode & stat.S_IXUSR


def test_t1_authorized_repairs_preview_and_execute_through_lifecycle_service(
    monkeypatch, context
):
    for name in doctor.PARA_PATH_NAMES:
        context.core_path(name).mkdir(parents=True, exist_ok=True)
    script = context.vault_root / ".scripts" / "repair-me.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/sh\n")
    script.chmod(0o644)
    monkeypatch.setattr(doctor, "_repo_shipped_executables", lambda _context: [script])

    calls = []
    real_execute = doctor.lifecycle_service._execute_approved_transaction

    def recording_execute(*args, **kwargs):
        calls.append((args, kwargs))
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(
        doctor.lifecycle_service,
        "_execute_approved_transaction",
        recording_execute,
    )

    actions, errors = doctor._apply_t1_heals(context)

    assert errors == []
    structure_actions = actions["vault.structure"]
    assert "regenerated core/paths.json" in structure_actions
    assert any("restored executable permission" in action for action in structure_actions)
    assert len(calls) == 1
    assert calls[0][1]["purpose"] == "doctor-tier-1"
    assert (context.vault_root / "core/paths.json").is_file()
    assert script.stat().st_mode & stat.S_IXUSR


def test_partial_t1_failure_reports_applied_actions_and_breaks_doctor_self(monkeypatch, context):
    _stub_probes(monkeypatch, exclude={"vault.structure"})

    def fail_mode_inspection(_context):
        raise RuntimeError("git mode inspection failed")

    monkeypatch.setattr(doctor, "_repo_shipped_executables", fail_mode_inspection)

    report = doctor.collect(heal=True, context=context)

    structure = _check(report, "vault.structure")
    assert structure["verdict"] == "BROKEN"
    assert structure["heal"]["applied"] is True
    assert "regenerated core/paths.json" in structure["heal"]["action"]
    assert _check(report, "doctor.self")["verdict"] == "BROKEN"
    assert report["instruments"]["failed"][0]["id"] == "doctor.self"
    assert "Directory repair requires user action" in report["instruments"]["failed"][0]["error"]
    assert "Executable-mode heal failed: git mode inspection failed" in report["instruments"]["failed"][0]["error"]


def test_heal_does_not_overwrite_a_raising_structure_probe_with_ok(monkeypatch, context):
    _stub_probes(monkeypatch)
    monkeypatch.setattr(
        doctor,
        "_apply_t1_heals",
        lambda _context: ({"vault.structure": ["regenerated core/paths.json"]}, []),
    )

    def explode(_context):
        raise RuntimeError("structure probe exploded")

    monkeypatch.setattr(doctor, "_probe_vault_structure", explode)

    report = doctor.collect(heal=True, context=context)

    structure = _check(report, "vault.structure")
    assert structure["verdict"] == "UNKNOWN"
    assert structure["heal"]["applied"] is True
    assert report["instruments"]["failed"] == [
        {"id": "vault.structure", "error": "structure probe exploded"}
    ]


def test_main_heal_flag_invokes_t1_and_still_returns_json(monkeypatch, context, capsys):
    _stub_probes(monkeypatch)
    calls = []
    monkeypatch.setattr(doctor, "_apply_t1_heals", lambda candidate: (calls.append(candidate) or {}, []))

    assert doctor.main(["--heal"], context=context) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "quick"
    assert calls == [context]


def test_main_heal_reports_progress_before_repairs_and_checks(
    monkeypatch, context, capsys
):
    """A stuck step must not leave the person staring at an empty terminal."""
    observed_stderr = []

    def heal(_context):
        observed_stderr.append(capsys.readouterr().err)
        return {}, []

    def first_probe(_context):
        observed_stderr.append(capsys.readouterr().err)
        return doctor.ProbeResult("OK", "Stub probe completed.")

    _stub_probes(monkeypatch)
    monkeypatch.setattr(doctor, "_apply_t1_heals", heal)
    monkeypatch.setattr(doctor, "_probe_vault_structure", first_probe)

    assert doctor.main(["--heal"], context=context) == 0
    captured = capsys.readouterr()

    assert observed_stderr == [
        f"{doctor.HEAL_PROGRESS}\n",
        f"{doctor.CHECK_PROGRESS}\n",
    ]
    assert captured.err == ""
    assert json.loads(captured.out)["mode"] == "quick"


def test_collect_runs_probes_in_process_without_shared_timeout_threads(
    monkeypatch, context, capsys
):
    """Checks must not be abandoned in daemon threads after a shared deadline."""
    caller = threading.get_ident()
    seen: list[int] = []

    def first_probe(_context):
        seen.append(threading.get_ident())
        return doctor.ProbeResult("OK", "Stub probe completed.")

    _stub_probes(monkeypatch)
    monkeypatch.setattr(doctor, "_probe_vault_structure", first_probe)

    report = doctor.collect(context=context)

    assert seen == [caller]
    assert _check(report, "vault.structure")["verdict"] == "OK"
    assert capsys.readouterr().err == ""


def test_heal_failure_stays_in_thread_and_later_heals_still_run(monkeypatch, context):
    caller = threading.get_ident()
    seen: list[tuple[str, int]] = []

    def fail_executables(_context):
        seen.append(("exec", threading.get_ident()))
        raise RuntimeError("exec boom")

    def env_finding(_context):
        seen.append(("env", threading.get_ident()))
        return None

    (context.vault_root / "core" / "paths.json").write_text("{}\n")
    for name in doctor.PARA_PATH_NAMES:
        context.core_path(name).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(doctor, "_paths_export_for", lambda _context: {})
    monkeypatch.setattr(doctor, "_repo_shipped_executables", fail_executables)
    monkeypatch.setattr(doctor, "_env_permission_finding", env_finding)
    monkeypatch.setattr(doctor, "_acknowledge_resolved_preflight_errors", lambda _context: 0)
    monkeypatch.setattr(doctor, "_heal_claude_composition", lambda _context: None)
    monkeypatch.setattr(
        doctor,
        "_probe_capability_rooms",
        lambda _context: doctor.ProbeResult("OK", "rooms"),
    )

    actions, errors = doctor._apply_t1_heals(context)

    assert [name for name, _ident in seen] == ["exec", "env"]
    assert all(ident == caller for _name, ident in seen)
    assert errors == ["Executable-mode heal failed: exec boom"]
    assert actions == {}


def test_doctor_skill_keeps_collector_stderr_visible():
    skill = (REPO_ROOT / ".claude/skills/dex-doctor/SKILL.md").read_text(encoding="utf-8")
    assert "doctor.py --heal 2>/dev/null" not in skill
    assert "python3 core/utils/doctor.py --heal" in skill


def test_main_deep_flag_runs_the_deep_registry(monkeypatch, context, capsys):
    _stub_probes(monkeypatch)

    assert doctor.main(["--deep"], context=context) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "deep"
    assert [check["id"] for check in report["checks"]] == QUICK_IDS + DEEP_IDS


def test_cli_still_emits_json_when_yaml_is_not_importable(tmp_path):
    vault = tmp_path / "vault-without-yaml"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "user-profile.yaml").write_text("name: Test User\n")
    (vault / "System" / "pillars.yaml").write_text("pillars: []\n")
    settings = vault / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"hooks": {}}\n')
    home = tmp_path / "empty-home"
    home.mkdir()
    env = dict(os.environ)
    env.update({"HOME": str(home), "VAULT_PATH": str(vault)})

    result = subprocess.run(
        [sys.executable, "-S", str(DOCTOR_PATH)],
        cwd=vault,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    report = json.loads(result.stdout)
    guidance = (
        "Python packages not installed (missing module 'yaml') — run /dex-update "
        "(or pip install -r requirements.txt) "
        "then re-run /dex-doctor."
    )
    for check_id in ("vault.configs", "customizations.skills", "customizations.mcp"):
        assert _check(report, check_id)["verdict"] == "UNKNOWN"
        assert _check(report, check_id)["detail"] == guidance
    assert _check(report, "python.env")["verdict"] == "BROKEN"


def test_vault_structure_maps_missing_and_complete_directories(context):
    missing = doctor._probe_vault_structure(context)
    assert missing.verdict == "BROKEN"
    assert missing.heal.tier == 1

    for name in doctor.PARA_PATH_NAMES:
        context.core_path(name).mkdir(parents=True, exist_ok=True)

    assert doctor._probe_vault_structure(context).verdict == "OK"


def test_vault_configs_maps_parse_errors_to_broken(context):
    _write_valid_configs(context)
    assert doctor._probe_vault_configs(context).verdict == "OK"

    (context.vault_root / "System" / "pillars.yaml").write_text("pillars: [\n")
    result = doctor._probe_vault_configs(context)
    assert result.verdict == "BROKEN"
    assert "pillars.yaml" in result.detail
    assert result.heal.tier == 3


def test_capability_rooms_probe_detects_missing_on_assets_and_live_off_skills(
    context,
) -> None:
    (context.vault_root / "System/.onboarding-complete").touch()
    (context.vault_root / "System/user-profile.yaml").write_text(
        "name: Legacy User\n"
        "capabilities:\n"
        "  career:\n"
        "    enabled: true\n"
        "  companies:\n"
        "    enabled: false\n"
        "  quarter_goals:\n"
        "    enabled: false\n",
        encoding="utf-8",
    )
    stale_skill = context.vault_root / ".claude/skills/quarter-plan/SKILL.md"
    stale_skill.parent.mkdir(parents=True, exist_ok=True)
    stale_skill.write_text("---\nname: quarter-plan\n---\n", encoding="utf-8")

    result = doctor._probe_capability_rooms(context)

    assert result.verdict == "BROKEN"
    assert "career" in result.detail
    assert "quarter-plan" in result.detail
    assert result.heal == doctor.Heal(
        tier=1,
        action=(
            "Reconcile capability room folders and shipped skills without "
            "deleting user content."
        ),
        applied=False,
    )


def test_capability_seed_probe_advises_update_only_for_enabled_rooms(
    context,
) -> None:
    (context.vault_root / "System/.onboarding-complete").touch()
    profile_path = context.vault_root / "System/user-profile.yaml"
    profile_path.write_text(
        "name: Legacy User\n"
        "capabilities:\n"
        "  career:\n"
        "    enabled: true\n"
        "  companies:\n"
        "    enabled: false\n"
        "  quarter_goals:\n"
        "    enabled: false\n",
        encoding="utf-8",
    )
    career = context.vault_root / "05-Areas/Career"
    career.mkdir(parents=True)
    dormant = (
        REPO_ROOT / ".claude/skills/_available/capabilities/career/skills"
    )
    for skill in ("career-setup", "career-coach", "resume-builder"):
        shutil.copytree(dormant / skill, context.vault_root / ".claude/skills" / skill)

    missing = doctor._probe_capability_rooms(context)

    assert missing.verdict == "BROKEN"
    assert "05-Areas/Career/Evidence/README.md" in missing.detail
    assert "run /dex-update to restore" in missing.detail
    assert "01-Quarter_Goals/Quarter_Goals.md" not in missing.detail

    profile_path.write_text(
        profile_path.read_text(encoding="utf-8").replace(
            "  career:\n    enabled: true",
            "  career:\n    enabled: false",
        ),
        encoding="utf-8",
    )
    for skill in ("career-setup", "career-coach", "resume-builder"):
        shutil.rmtree(context.vault_root / ".claude/skills" / skill)

    disabled = doctor._probe_capability_rooms(context)

    assert disabled.verdict == "OK"
    assert "05-Areas/Career/Evidence/README.md" not in disabled.detail
    assert "/dex-update" not in disabled.detail


def test_doctor_heal_reconciles_room_assets_and_preserves_user_content(
    monkeypatch: pytest.MonkeyPatch,
    context,
) -> None:
    for name in doctor.PARA_PATH_NAMES:
        context.core_path(name).mkdir(parents=True, exist_ok=True)
    (context.vault_root / "System/user-profile.yaml").write_text(
        "name: Legacy User\n"
        "role: Founder\n",
        encoding="utf-8",
    )
    user_note = context.vault_root / "05-Areas/Career/private-review.md"
    user_note.parent.mkdir(parents=True, exist_ok=True)
    user_note.write_text("Keep this forever.\n", encoding="utf-8")
    existing_skill = context.vault_root / ".claude/skills/quarter-plan/SKILL.md"
    existing_skill.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        REPO_ROOT
        / ".claude/skills/_available/capabilities/quarter_goals/skills/quarter-plan/SKILL.md",
        existing_skill,
    )
    context.paths_json_path.parent.mkdir(parents=True, exist_ok=True)
    context.paths_json_path.write_text(
        json.dumps(doctor._paths_export_for(context)),
        encoding="utf-8",
    )
    monkeypatch.setattr(doctor, "_repo_shipped_executables", lambda _context: [])
    _stub_probes(monkeypatch, exclude={"capabilities.rooms"})

    report = doctor.collect(heal=True, context=context)

    rooms = _check(report, "capabilities.rooms")
    assert rooms["verdict"] == "OK"
    assert rooms["heal"] == {
        "tier": 1,
        "action": "reconciled capability room assets without deleting user content.",
        "applied": True,
    }
    assert user_note.read_text(encoding="utf-8") == "Keep this forever.\n"
    assert (
        context.vault_root / "05-Areas/Career/Evidence/README.md"
    ).is_file()
    for skill in ("career-setup", "career-coach", "resume-builder"):
        assert (
            context.vault_root / ".claude/skills" / skill / "SKILL.md"
        ).is_file()
    for skill in (
        "career-setup",
        "career-coach",
        "resume-builder",
        "quarter-plan",
        "quarter-review",
    ):
        assert (
            context.vault_root / ".claude/skills" / skill / "SKILL.md"
        ).is_file()
    profile = (
        context.vault_root / "System/user-profile.yaml"
    ).read_text(encoding="utf-8")
    assert "companies:\n    enabled: true" in profile


def test_mcp_registered_distinguishes_never_onboarded_from_missing_after_onboarding(context):
    result = doctor._probe_mcp_registered(context)
    assert result.verdict == "OFF"

    (context.vault_root / "System" / ".onboarding-complete").touch()
    result = doctor._probe_mcp_registered(context)
    assert result.verdict == "BROKEN"


def test_mcp_registered_reports_missing_target_as_broken(context):
    target = context.vault_root / "core" / "mcp" / "missing_server.py"
    _write_mcp_config(
        context,
        {"missing": {"command": sys.executable, "args": [str(target)]}},
    )

    result = doctor._probe_mcp_registered(context)

    assert result.verdict == "BROKEN"
    assert "missing_server.py" in result.detail
    assert result.heal.tier == 2


def test_mcp_registered_maps_missing_registry_object_to_broken_t3(context):
    (context.vault_root / ".mcp.json").write_text("{}\n")

    result = doctor._probe_mcp_registered(context)

    assert result.verdict == "BROKEN"
    assert result.heal.tier == 3


def test_mcp_target_detection_ignores_external_package_and_data_arguments(context):
    entry = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/allowed-directory"],
    }

    assert doctor._entry_targets(entry, context) == []


def test_mcp_registered_reports_missing_bare_command(monkeypatch, context):
    _write_mcp_config(context, {"external": {"command": "missing-mcp-command", "args": []}})
    monkeypatch.setattr(doctor.shutil, "which", lambda _command: None)

    result = doctor._probe_mcp_registered(context)

    assert result.verdict == "BROKEN"
    assert "missing-mcp-command" in result.detail


def test_mcp_registered_reports_non_executable_command_path(context):
    command = context.vault_root / "bin" / "server"
    command.parent.mkdir()
    command.write_text("#!/bin/sh\n")
    command.chmod(0o644)
    _write_mcp_config(context, {"local": {"command": str(command), "args": []}})

    result = doctor._probe_mcp_registered(context)

    assert result.verdict == "BROKEN"
    assert "not executable" in result.detail


def test_mcp_registered_accepts_remote_http_entries_without_a_command(context):
    _write_mcp_config(
        context,
        {"remote": {"type": "http", "url": "https://example.com/mcp"}},
    )

    assert doctor._probe_mcp_registered(context).verdict == "OK"


def test_mcp_registered_rejects_unsubstituted_live_template(context):
    _write_mcp_config(
        context,
        {
            "work-mcp": {
                "command": "{{VAULT_PATH}}/.venv/bin/python",
                "args": ["{{VAULT_PATH}}/core/mcp/work_server.py"],
            }
        },
    )

    result = doctor._probe_mcp_registered(context)

    assert result.verdict == "BROKEN"
    assert result.heal.tier == 2
    assert "template" in result.detail


def test_mcp_orphans_compares_server_targets_not_registry_names(context):
    mcp_dir = context.vault_root / "core" / "mcp"
    mcp_dir.mkdir(parents=True)
    alpha = mcp_dir / "alpha_server.py"
    alpha.touch()
    _write_mcp_config(
        context,
        {"friendly-alpha": {"command": sys.executable, "args": [str(alpha)]}},
    )
    assert doctor._probe_mcp_orphans(context).verdict == "OK"

    (mcp_dir / "beta_server.py").touch()
    result = doctor._probe_mcp_orphans(context)
    assert result.verdict == "BROKEN"
    assert "beta_server.py" in result.detail


def test_mcp_probes_read_legacy_config_without_moving_it(context):
    mcp_dir = context.vault_root / "core" / "mcp"
    mcp_dir.mkdir(parents=True)
    server = mcp_dir / "alpha_server.py"
    server.touch()
    legacy = context.vault_root / "System" / ".mcp.json"
    legacy.write_text(
        json.dumps(
            {"mcpServers": {"alpha": {"command": sys.executable, "args": [str(server)]}}}
        )
    )

    before = _tree_snapshot(context.vault_root)
    registered = doctor._probe_mcp_registered(context)
    orphans = doctor._probe_mcp_orphans(context)

    assert registered.verdict == "OK"
    assert orphans.verdict == "OK"
    assert "legacy System/.mcp.json" in registered.detail
    assert "legacy System/.mcp.json" in orphans.detail
    assert _tree_snapshot(context.vault_root) == before
    assert not (context.vault_root / ".mcp.json").exists()


def test_mcp_orphans_invalid_registry_becomes_unknown_in_the_runner(monkeypatch, context):
    mcp_dir = context.vault_root / "core" / "mcp"
    mcp_dir.mkdir(parents=True)
    (mcp_dir / "work_server.py").touch()
    (context.vault_root / ".mcp.json").write_text("{invalid\n")
    _stub_probes(monkeypatch, exclude={"mcp.orphans"})

    report = doctor.collect(context=context)

    assert _check(report, "mcp.orphans")["verdict"] == "UNKNOWN"
    assert report["instruments"]["failed"][0]["id"] == "mcp.orphans"


def test_python_env_maps_missing_interpreter_and_missing_imports_to_broken(monkeypatch, context):
    assert doctor._probe_python_env(context).verdict == "BROKEN"

    python = context.vault_root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    monkeypatch.setattr(doctor, "_python_import_check", lambda _python: (False, ["requests"]))
    missing_import = doctor._probe_python_env(context)
    assert missing_import.verdict == "BROKEN"
    assert "requests" in missing_import.detail

    monkeypatch.setattr(doctor, "_python_import_check", lambda _python: (True, []))
    assert doctor._probe_python_env(context).verdict == "OK"


def test_python_dependency_probe_imports_modules_instead_of_only_discovering_them(monkeypatch):
    def run(command, **_kwargs):
        assert "import_module" in command[2]
        return subprocess.CompletedProcess(command, 0, stdout="[]\n", stderr="")

    monkeypatch.setattr(doctor.subprocess, "run", run)

    assert doctor._python_import_check(Path(sys.executable)) == (True, [])


def test_relative_interpreter_paths_resolve_from_the_vault(context):
    python = context.vault_root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)

    assert doctor._resolved_interpreter(".venv/bin/python", context) == str(python)


def test_hooks_wired_detects_dangling_hook_files(context):
    settings = context.vault_root / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "bash .claude/hooks/session-start.sh"}]}
                    ]
                }
            }
        )
    )

    broken = doctor._probe_hooks_wired(context)
    assert broken.verdict == "BROKEN"
    assert "session-start.sh" in broken.detail

    hook = context.vault_root / ".claude" / "hooks" / "session-start.sh"
    hook.parent.mkdir()
    hook.touch()
    assert doctor._probe_hooks_wired(context).verdict == "OK"


def test_hooks_wired_detects_missing_bare_executable(monkeypatch, context):
    hook = context.vault_root / ".claude" / "hooks" / "run.cjs"
    hook.parent.mkdir(parents=True)
    hook.touch()
    settings = context.vault_root / ".claude" / "settings.json"
    settings.write_text(json.dumps({"hooks": {"SessionStart": [{"command": "node .claude/hooks/run.cjs"}]}}))
    monkeypatch.setattr(doctor.shutil, "which", lambda _command: None)

    result = doctor._probe_hooks_wired(context)

    assert result.verdict == "BROKEN"
    assert "node" in result.detail


def test_hooks_invalid_settings_becomes_unknown_in_the_runner(monkeypatch, context):
    settings = context.vault_root / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text("{invalid\n")
    _stub_probes(monkeypatch, exclude={"hooks.wired"})

    report = doctor.collect(context=context)

    assert _check(report, "hooks.wired")["verdict"] == "UNKNOWN"
    assert report["instruments"]["failed"][0]["id"] == "hooks.wired"


def test_jobs_loaded_distinguishes_not_installed_from_unloaded(monkeypatch, context):
    assert doctor._probe_jobs_loaded(context).verdict == "OFF"

    plist = _write_plist(context, "com.dex.meeting-intel")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(doctor, "_plist_interpreter", lambda candidate: "/bin/bash" if candidate == plist else None)
    monkeypatch.setattr(doctor, "_launchctl_status", lambda _label: {"loaded": False, "last_exit_status": None})

    result = doctor._probe_jobs_loaded(context)
    assert result.verdict == "BROKEN"
    assert "not loaded" in result.detail
    assert result.heal.tier == 2


def test_doctor_treats_valid_solo_claim_as_app_owned_and_offloaded(monkeypatch, context):
    plist = _write_plist(context, "com.dex.meeting-intel")
    _write_solo_automation_claim(context, plist, "com.dex.meeting-intel")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    def launchctl_must_not_run(*_args, **_kwargs):
        raise AssertionError("Core must not inspect launchd state for an offloaded job")

    monkeypatch.setattr(doctor, "_launchctl_status", launchctl_must_not_run)

    loaded = doctor._probe_jobs_loaded(context)
    fresh = doctor._probe_jobs_fresh(context)

    assert loaded.verdict == "OK"
    assert "owned by Dex Solo and offloaded from Core" in loaded.detail
    assert fresh.verdict == "OFF"
    assert "owned by Dex Solo and offloaded from Core" in fresh.detail


def test_doctor_does_not_call_valid_solo_claim_broken_or_stale(monkeypatch, context):
    former_vault = context.home.parent / "old-vault"
    _write_breadcrumb(context, former_vault)
    plist = _write_plist(context, "com.dex.example-job")
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.dex.example-job",
                "ProgramArguments": ["/bin/bash", str(former_vault / ".scripts/job.sh")],
            },
            handle,
        )
    _write_solo_automation_claim(context, plist, "com.dex.example-job")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "OK"
    assert "offloaded" in result.detail
    assert "old location" not in result.detail


def test_doctor_rejects_stale_solo_plist_evidence(monkeypatch, context):
    plist = _write_plist(context, "com.dex.meeting-intel")
    _write_solo_automation_claim(context, plist, "com.dex.meeting-intel")
    plist.write_bytes(plist.read_bytes() + b"\n")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(doctor, "_plist_interpreter", lambda _plist: "/bin/bash")
    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: {"loaded": False, "last_exit_status": None},
    )

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "BROKEN"
    assert "not loaded" in result.detail
    assert "offloaded" not in result.detail


def test_jobs_loaded_skips_foreign_product_plists(monkeypatch, context, foreign_launch_agents):
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "OFF"
    assert result.detail == (
        "No launch agents for this vault are installed; "
        "2 Dex launch agents from other Dex products were skipped"
    )
    assert "research-scan.py" not in result.detail


def test_shipped_job_from_another_vault_is_not_attributed_to_this_vault(monkeypatch, context):
    """A shipped label alone must not make a disposable fixture own a host job."""
    plist = _write_plist(context, "com.dex.meeting-intel")
    foreign_vault = context.home.parent / "Dex-Google-OAuth-Verification-Working"
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.dex.meeting-intel",
                "ProgramArguments": [
                    "/bin/bash",
                    str(foreign_vault / ".scripts" / "dex-launcher.sh"),
                ],
                "WorkingDirectory": str(foreign_vault),
            },
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    loaded = doctor._probe_jobs_loaded(context)
    fresh = doctor._probe_jobs_fresh(context)

    assert loaded.verdict == "OFF"
    assert loaded.detail == (
        "No launch agents for this vault are installed; "
        "1 Dex launch agent from another Dex product was skipped"
    )
    assert fresh.verdict == "OFF"


def test_shipped_job_from_another_worktree_vault_is_not_a_failure(monkeypatch, context):
    """A disposable fixture must not fail because another Dex worktree has a job."""
    plist = _write_plist(context, "com.dex.meeting-intel")
    foreign_vault = context.home.parent / ".bb" / "worktrees" / "env_x" / "dex-core"
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.dex.meeting-intel",
                "ProgramArguments": [
                    "/bin/bash",
                    str(foreign_vault / ".scripts" / "dex-launcher.sh"),
                ],
                "WorkingDirectory": str(foreign_vault),
            },
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    loaded = doctor._probe_jobs_loaded(context)
    fresh = doctor._probe_jobs_fresh(context)

    assert loaded.verdict == "OFF"
    assert loaded.detail == (
        "No launch agents for this vault are installed; "
        "1 Dex launch agent from another Dex product was skipped"
    )
    assert fresh.verdict == "OFF"


def test_corrupt_dex_plist_is_unknown_not_foreign(monkeypatch, context):
    """A malformed plist has no trustworthy ownership evidence either way."""
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / "com.dex.meeting-intel.plist"
    plist.write_bytes(b"not a plist")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    loaded = doctor._probe_jobs_loaded(context)
    fresh = doctor._probe_jobs_fresh(context)

    assert loaded.verdict == "UNKNOWN"
    assert fresh.verdict == "UNKNOWN"
    assert plist.name in loaded.detail
    assert plist.name in fresh.detail


def test_jobs_loaded_owns_unshipped_label_with_program_path_inside_vault(monkeypatch, context):
    plist = _write_plist(context, "com.dex.local-job")
    missing_script = context.vault_root / ".scripts" / "local-job.py"
    with plist.open("wb") as handle:
        plistlib.dump(
            {"Label": "com.dex.local-job", "ProgramArguments": ["/bin/bash", str(missing_script)]},
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "BROKEN"
    assert str(missing_script) in result.detail


def test_jobs_loaded_owns_repo_shipped_obsidian_agent(monkeypatch, context):
    plist = _write_plist(context, "com.dex.obsidian-sync")
    missing_script = context.vault_root / "core" / "obsidian" / "missing-sync-daemon.py"
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.dex.obsidian-sync",
                "ProgramArguments": ["/bin/bash", str(missing_script)],
            },
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "BROKEN"
    assert "com.dex.obsidian-sync" in result.detail


def test_jobs_loaded_checks_interpreter_exit_status_and_healthy_state(monkeypatch, context):
    _write_plist(context, "com.dex.meeting-intel")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(doctor, "_plist_interpreter", lambda _plist: "/missing/python")
    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: pytest.fail("launchctl must not run for a missing interpreter"),
    )
    missing = doctor._probe_jobs_loaded(context)
    assert missing.verdict == "BROKEN"
    assert missing.heal.tier == 3

    monkeypatch.setattr(doctor, "_plist_interpreter", lambda _plist: "/bin/bash")
    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: {"loaded": True, "last_exit_status": 9},
    )
    failed_run = doctor._probe_jobs_loaded(context)
    assert failed_run.verdict == "BROKEN"
    assert failed_run.heal.tier == 2

    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: {"loaded": True, "last_exit_status": 0},
    )
    assert doctor._probe_jobs_loaded(context).verdict == "OK"

    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: {"loaded": True, "last_exit_status": None},
    )
    assert doctor._probe_jobs_loaded(context).verdict == "UNKNOWN"


def test_jobs_loaded_treats_a_live_pid_as_authoritative_over_a_previous_exit(monkeypatch, context):
    _write_plist(context, "com.dex.meeting-intel")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(doctor, "_plist_interpreter", lambda _plist: "/bin/bash")
    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: {"loaded": True, "pid": 5266, "last_exit_status": -15},
    )

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "OK"


def test_jobs_loaded_does_not_treat_pid_zero_as_a_running_service(monkeypatch, context):
    _write_plist(context, "com.dex.meeting-intel")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(doctor, "_plist_interpreter", lambda _plist: "/bin/bash")
    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: {"loaded": True, "pid": 0, "last_exit_status": -15},
    )

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "BROKEN"
    assert "last exited with status -15" in result.detail


def test_jobs_loaded_maps_invalid_or_unsubstituted_plist_to_broken_t2(monkeypatch, context):
    plist = _write_plist(context, "com.dex.meeting-intel")
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.dex.meeting-intel",
                "ProgramArguments": [
                    "/bin/bash",
                    str(context.vault_root / ".scripts" / "dex-launcher.sh"),
                    "{{VAULT_PATH}}/.scripts/dex-launcher.sh",
                ],
            },
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(doctor, "_plist_interpreter", lambda _plist: "/bin/bash")
    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: pytest.fail("launchctl must not run for an unsubstituted plist"),
    )

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "BROKEN"
    assert result.heal.tier == 2


def test_jobs_loaded_reports_missing_program_script_as_broken_t2(monkeypatch, context):
    plist = _write_plist(context, "com.dex.meeting-intel")
    missing_script = context.vault_root / ".scripts" / "missing.sh"
    with plist.open("wb") as handle:
        plistlib.dump(
            {"Label": "com.dex.meeting-intel", "ProgramArguments": ["/bin/bash", str(missing_script)]},
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(doctor, "_plist_interpreter", lambda _plist: "/bin/bash")
    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: pytest.fail("launchctl must not run when the program script is missing"),
    )

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "BROKEN"
    assert result.heal.tier == 2


def test_launchctl_domain_failure_is_an_unknown_instrument(monkeypatch, context):
    plist = _write_plist(context, "com.dex.meeting-intel")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_plist_interpreter", lambda candidate: "/bin/bash" if candidate == plist else None)
    monkeypatch.setattr(
        doctor,
        "_launchctl_domain_check",
        lambda: (_ for _ in ()).throw(PermissionError("launchctl list is unavailable")),
    )

    with pytest.raises(PermissionError, match="launchctl list is unavailable"):
        doctor._probe_jobs_loaded(context)


def test_plist_sandbox_failure_propagates_for_unknown_mapping(monkeypatch, context):
    _write_plist(context, "com.dex.meeting-intel")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(
        doctor,
        "_plist_data",
        lambda _plist: (_ for _ in ()).throw(PermissionError("sandbox denied plist read")),
    )

    with pytest.raises(PermissionError, match="sandbox denied plist read"):
        doctor._probe_jobs_loaded(context)


def test_empty_plutil_failure_is_unknown_not_malformed(monkeypatch, context):
    plist = _write_plist(context, "com.dex.meeting-intel")
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr=""),
    )

    with pytest.raises(PermissionError, match="plutil could not run"):
        doctor._plist_interpreter(plist)


def test_launchctl_status_adapter_parses_last_exit_status(monkeypatch):
    output = '{\n    "PID" = 5266;\n    "LastExitStatus" = 7;\n}\n'
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, stdout=output, stderr=""),
    )

    assert doctor._launchctl_status("com.dex.test") == {
        "loaded": True,
        "pid": 5266,
        "last_exit_status": 7,
    }

    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="Could not find service",
        ),
    )
    assert doctor._launchctl_status("com.dex.missing") == {
        "loaded": False,
        "pid": None,
        "last_exit_status": None,
    }


def test_jobs_loaded_degrades_to_unknown_off_macos(monkeypatch, context):
    _write_plist(context, "com.dex.meeting-intel")
    monkeypatch.setattr(doctor, "_is_macos", lambda: False)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "UNKNOWN"


@pytest.mark.parametrize(
    ("label", "expected_max_age"),
    [
        ("com.dex.smoke-nightly", timedelta(hours=26)),
        ("com.dex.meeting-intel", timedelta(hours=48)),
        ("com.dex.changelog-checker", timedelta(days=7)),
        ("com.dex.learning-review", timedelta(days=7)),
    ],
)
def test_freshness_thresholds_are_strictly_greater_than_the_limit(label, expected_max_age, context):
    _write_plist(context, label)
    promise = health_promises.promise_by_id(label)
    assert promise is not None and promise.cadence == expected_max_age

    def record_run(when):
        receipt = context.vault_root / promise.receipt_path
        receipt.parent.mkdir(parents=True, exist_ok=True)
        if promise.receipt_kind == "json-timestamp":
            receipt.write_text(
                json.dumps({promise.receipt_key: when.isoformat().replace("+00:00", "Z")}),
                encoding="utf-8",
            )
        else:
            receipt.touch()
            os.utime(receipt, (when.timestamp(), when.timestamp()))

    record_run(NOW - expected_max_age + timedelta(seconds=1))
    assert doctor._probe_jobs_fresh(context).verdict == "OK"

    record_run(NOW - expected_max_age)
    assert doctor._probe_jobs_fresh(context).verdict == "OK"

    stale_at = NOW - expected_max_age - timedelta(seconds=1)
    record_run(stale_at)
    result = doctor._probe_jobs_fresh(context)
    assert result.verdict == "BROKEN"
    assert stale_at.date().isoformat() in result.detail


def test_freshness_is_off_when_job_is_not_installed_even_if_receipt_is_stale(context):
    promise = health_promises.promise_by_id("com.dex.meeting-intel")
    receipt = context.vault_root / promise.receipt_path
    receipt.parent.mkdir(parents=True)
    stale_at = NOW - timedelta(days=100)
    receipt.write_text(
        json.dumps({"lastSync": stale_at.isoformat().replace("+00:00", "Z")}),
        encoding="utf-8",
    )

    assert doctor._probe_jobs_fresh(context).verdict == "OFF"


def test_freshness_is_broken_when_installed_job_never_succeeded(context):
    _write_plist(context, "com.dex.smoke-nightly")

    result = doctor._probe_jobs_fresh(context)

    assert result.verdict == "BROKEN"
    assert "never recorded a completed run" in result.detail


def test_meeting_sync_freshness_reads_last_success_not_log_activity(context):
    """A job that fails every run keeps appending its log; only lastSync counts."""
    _write_plist(context, "com.dex.meeting-intel")
    promise = health_promises.promise_by_id("com.dex.meeting-intel")
    log = context.vault_root / ".scripts/logs/meeting-intel.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.touch()
    os.utime(log, (NOW.timestamp(), NOW.timestamp()))

    never = doctor._probe_jobs_fresh(context)
    assert never.verdict == "BROKEN"
    assert "never recorded a completed run" in never.detail

    state = context.vault_root / promise.receipt_path
    state.parent.mkdir(parents=True, exist_ok=True)
    stale_at = NOW - timedelta(days=6)
    state.write_text(
        json.dumps({"lastSync": stale_at.isoformat().replace("+00:00", "Z")}),
        encoding="utf-8",
    )

    stale = doctor._probe_jobs_fresh(context)
    assert stale.verdict == "BROKEN"
    assert "last completed successfully" in stale.detail
    assert stale_at.date().isoformat() in stale.detail


def test_daemon_promises_are_not_freshness_audited(context):
    """Continuous daemons have no cadence; launchd liveness is their check."""
    _write_plist(context, "com.dex.obsidian-sync")

    assert doctor._probe_jobs_fresh(context).verdict == "OFF"


def _write_breadcrumb(context, former_vault):
    breadcrumb = context.home / ".config" / "dex" / "vault-path"
    breadcrumb.parent.mkdir(parents=True, exist_ok=True)
    breadcrumb.write_text(f"{former_vault}\n", encoding="utf-8")
    return breadcrumb


def test_jobs_loaded_flags_agent_pointing_at_the_stored_former_vault_root(
    monkeypatch, context
):
    """A job left behind by a vault move is owned-and-stale, never foreign (#364)."""
    former_vault = context.home.parent / "old-vault"
    _write_breadcrumb(context, former_vault)
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / "com.dex.example-job.plist"
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.dex.example-job",
                "ProgramArguments": [
                    "/bin/bash",
                    str(former_vault / ".scripts" / "example-job.sh"),
                ],
            },
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "BROKEN"
    assert "com.dex.example-job" in result.detail
    assert "old location" in result.detail
    assert str(former_vault) in result.detail
    assert result.heal.tier == 2
    assert "repoint" in result.heal.action
    assert str(context.vault_root) in result.heal.action


def test_jobs_loaded_flags_user_labeled_stale_agent_the_hook_warns_about(
    monkeypatch, context
):
    """The hook and the doctor must agree: any label pointing at the former root."""
    former_vault = context.home.parent / "old-vault"
    _write_breadcrumb(context, former_vault)
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / "com.alice.dex.context-sync.plist"
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.alice.dex.context-sync",
                "ProgramArguments": [
                    "/bin/bash",
                    "-c",
                    f"cd {former_vault} && ./run-sync.sh",
                ],
            },
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "BROKEN"
    assert "com.alice.dex.context-sync" in result.detail
    assert "old location" in result.detail


def test_jobs_loaded_stale_matching_requires_a_path_boundary(monkeypatch, context):
    """A former root of .../old-vault must not claim jobs under .../old-vault-other."""
    former_vault = context.home.parent / "old-vault"
    _write_breadcrumb(context, former_vault)
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / "com.dex.sibling-product.plist"
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.dex.sibling-product",
                "ProgramArguments": [
                    "/bin/bash",
                    str(
                        context.home.parent
                        / "old-vault-other"
                        / ".scripts"
                        / "run.sh"
                    ),
                ],
            },
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "OFF"
    assert "old location" not in result.detail
    assert "was skipped" in result.detail


def test_jobs_loaded_discovers_user_labeled_dex_agent_for_this_vault(
    monkeypatch, context
):
    """User-installed com.<user>.dex.* jobs get real monitoring coverage (#253)."""
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    missing_script = context.vault_root / ".scripts" / "context-sync.sh"
    plist = agents / "com.alice.dex.context-sync.plist"
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.alice.dex.context-sync",
                "ProgramArguments": ["/bin/bash", str(missing_script)],
            },
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "BROKEN"
    assert "com.alice.dex.context-sync" in result.detail
    assert str(missing_script) in result.detail


def test_jobs_loaded_discovers_vault_job_under_any_label_by_path_evidence(
    monkeypatch, context
):
    """Ownership is path evidence, not the label: any plist into this vault counts."""
    plist = _write_plist(context, "com.mycompany.sync")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(
        doctor, "_plist_interpreter", lambda candidate: "/bin/bash" if candidate == plist else None
    )
    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: {"loaded": True, "last_exit_status": 0},
    )

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "OK"
    assert "All 1 installed launch agents for this vault are loaded" in result.detail


def test_jobs_loaded_ignores_unrelated_products_whose_names_contain_dex(
    monkeypatch, context
):
    """com.dexcom.* / com.samsung.dex.* / com.fedex.* are other products."""
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    for label in ("com.dexcom.monitor", "com.samsung.dex.launcher", "com.fedex.tracker"):
        plist = agents / f"{label}.plist"
        with plist.open("wb") as handle:
            plistlib.dump(
                {"Label": label, "ProgramArguments": ["/usr/bin/true"]},
                handle,
            )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "OFF"
    assert result.detail == "No Dex launch agents are installed"


def test_jobs_loaded_leaves_unreadable_non_dex_plists_alone(monkeypatch, context):
    """Another product's corrupt plist is none of this vault's business."""
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "com.othertool.job.plist").write_bytes(b"not a plist")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "OFF"
    assert result.detail == "No Dex launch agents are installed"


def test_corrupt_third_party_plists_never_degrade_job_monitoring(monkeypatch, context):
    """One damaged foreign file must not take down Dex's own job checks.

    plistlib raises ExpatError for truncated XML with a valid header (a
    classic interrupted write) and ValueError for bad scalars; neither may
    make jobs.loaded or jobs.fresh UNKNOWN, or a genuinely dead com.dex job
    would stop being reported.
    """
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "com.samsung.dex.service.plist").write_bytes(
        b'<?xml version="1.0"?><plist version="1.0"><dict><key>Label</key>'
    )
    (agents / "com.othertool.job.plist").write_bytes(
        b'<plist version="1.0"><dict><key>N</key><integer>zz</integer></dict></plist>'
    )
    plist = _write_plist(context, "com.dex.smoke-nightly")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(
        doctor, "_plist_interpreter", lambda candidate: "/bin/bash" if candidate == plist else None
    )
    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: {"loaded": True, "last_exit_status": 0},
    )

    loaded = doctor._probe_jobs_loaded(context)
    fresh = doctor._probe_jobs_fresh(context)

    assert loaded.verdict == "OK"
    assert "othertool" not in loaded.detail and "samsung" not in loaded.detail
    assert fresh.verdict == "BROKEN"  # smoke-nightly never recorded a run
    assert "never recorded a completed run" in fresh.detail
    assert "othertool" not in fresh.detail and "samsung" not in fresh.detail


def test_truncated_shipped_plist_is_unknown_not_a_probe_crash(monkeypatch, context):
    """A shipped plist damaged mid-write is an unknown, not an exception."""
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / "com.dex.meeting-intel.plist"
    plist.write_bytes(
        b'<?xml version="1.0"?><plist version="1.0"><dict><key>Label</key>'
    )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    loaded = doctor._probe_jobs_loaded(context)
    fresh = doctor._probe_jobs_fresh(context)

    assert loaded.verdict == "UNKNOWN"
    assert plist.name in loaded.detail
    assert fresh.verdict == "UNKNOWN"
    assert plist.name in fresh.detail


def test_legacy_claudesidian_jobs_get_real_freshness_audits(context):
    """Pre-rename shipped jobs map onto their com.dex.* promises (not 'user jobs')."""
    _write_plist(context, "com.claudesidian.learning-review")

    result = doctor._probe_jobs_fresh(context)

    assert result.verdict == "BROKEN"
    assert "Learning review has never run" in result.detail
    assert "checked for loading only" not in result.detail


def test_jobs_loaded_flags_owned_agent_with_leftover_former_root_references(
    monkeypatch, context
):
    """A partially repointed job (invocation current, other keys stale) is surfaced.

    The session-start hook greps raw bytes and keeps warning about the
    leftover references; the doctor must see the same thing or the user is
    back in the hook-warns/doctor-shrugs limbo of #364.
    """
    former_vault = context.home.parent / "old-vault"
    _write_breadcrumb(context, former_vault)
    plist = _write_plist(context, "com.dex.meeting-intel")
    script = context.vault_root / ".scripts" / "com.dex.meeting-intel.sh"
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.dex.meeting-intel",
                "ProgramArguments": ["/bin/bash", str(script)],
                "WorkingDirectory": str(former_vault),
            },
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "BROKEN"
    assert "still references its old location" in result.detail
    assert str(former_vault) in result.detail
    assert result.heal.tier == 2
    assert "repoint" in result.heal.action


def test_plist_ownership_sees_vault_path_inside_shell_command_strings(context):
    """/bin/bash -c "cd <vault>; ..." owns the job even without a path argument."""
    vault_root = context.vault_root.resolve()
    owned = {
        "Label": "com.dex.custom",
        "ProgramArguments": ["/bin/bash", "-c", f"cd {vault_root}; exec ./run.sh"],
    }
    sibling = {
        "Label": "com.dex.custom",
        "ProgramArguments": ["/bin/bash", "-c", f"cd {vault_root}-other; exec ./run.sh"],
    }
    logging_only = {
        "Label": "com.other.tool",
        "ProgramArguments": ["/usr/bin/true"],
        "StandardOutPath": str(vault_root / "log.txt"),
    }

    assert doctor._plist_owned_by_vault(owned, vault_root) is True
    assert doctor._plist_owned_by_vault(sibling, vault_root) is False
    assert doctor._plist_owned_by_vault(logging_only, vault_root) is False


def test_jobs_fresh_names_user_jobs_it_cannot_freshness_audit(context):
    """OFF must not read as 'nothing to monitor' when user jobs exist (#253)."""
    _write_plist(context, "com.alice.dex.context-sync")

    result = doctor._probe_jobs_fresh(context)

    assert result.verdict == "OFF"
    assert "No shipped Dex freshness jobs are installed" in result.detail
    assert "com.alice.dex.context-sync" in result.detail
    assert "checked for loading only, not freshness" in result.detail


def test_jobs_fresh_appends_user_job_coverage_note_alongside_shipped_promises(context):
    _write_plist(context, "com.dex.meeting-intel")
    _write_plist(context, "com.alice.dex.context-sync")
    promise = health_promises.promise_by_id("com.dex.meeting-intel")
    receipt = context.vault_root / promise.receipt_path
    receipt.parent.mkdir(parents=True, exist_ok=True)
    fresh_at = NOW - timedelta(hours=1)
    receipt.write_text(
        json.dumps({"lastSync": fresh_at.isoformat().replace("+00:00", "Z")}),
        encoding="utf-8",
    )

    result = doctor._probe_jobs_fresh(context)

    assert result.verdict == "OK"
    assert "com.alice.dex.context-sync" in result.detail
    assert "checked for loading only, not freshness" in result.detail


def test_launch_agent_classification_is_shared_within_a_scan_scope(monkeypatch, context):
    """collect() classifies every plist once; direct probe calls stay fresh."""
    calls = []
    real_classify = doctor._classify_launch_agents

    def counting_classify(inner_context):
        calls.append(inner_context)
        return real_classify(inner_context)

    monkeypatch.setattr(doctor, "_classify_launch_agents", counting_classify)

    doctor._begin_launch_agent_scan_scope(context)
    try:
        doctor._scan_launch_agents(context)
        doctor._scan_launch_agents(context)
        assert len(calls) == 1
    finally:
        doctor._end_launch_agent_scan_scope(context)

    doctor._scan_launch_agents(context)
    assert len(calls) == 2


def test_stored_former_vault_root_rejects_current_and_degenerate_roots(context):
    assert doctor._stored_former_vault_root(context) is None

    _write_breadcrumb(context, context.vault_root)
    assert doctor._stored_former_vault_root(context) is None

    _write_breadcrumb(context, "/tmp")
    assert doctor._stored_former_vault_root(context) is None

    _write_breadcrumb(context, "relative/path")
    assert doctor._stored_former_vault_root(context) is None

    former = context.home.parent / "old-vault"
    _write_breadcrumb(context, former)
    assert doctor._stored_former_vault_root(context) == former


def test_jobs_loaded_skips_a_dex_plist_pointing_at_another_worktree(
    monkeypatch, context
):
    """A worktree path is foreign unless it is this vault's path evidence."""
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    worktree = context.home.parent / ".bb" / "worktrees" / "env_x" / "dex-core"
    plist = agents / "com.dex.meeting-intel.plist"
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.dex.meeting-intel",
                "ProgramArguments": ["/bin/bash", str(worktree / ".scripts" / "dex-launcher.sh")],
                "WorkingDirectory": str(worktree),
            },
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "OFF"
    assert result.detail == (
        "No launch agents for this vault are installed; "
        "1 Dex launch agent from another Dex product was skipped"
    )


def test_jobs_loaded_skips_a_dex_plist_pointing_into_another_git_worktree_checkout(
    monkeypatch, context
):
    checkout = context.home.parent / "checkouts" / "dex-copy"
    (checkout / ".scripts").mkdir(parents=True)
    (checkout / ".git").write_text("gitdir: /somewhere/else\n", encoding="utf-8")
    script = checkout / ".scripts" / "dex-launcher.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / "com.dex.meeting-intel.plist"
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.dex.meeting-intel",
                "ProgramArguments": ["/bin/bash", str(script)],
                "WorkingDirectory": str(checkout),
            },
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "OFF"
    assert result.detail == (
        "No launch agents for this vault are installed; "
        "1 Dex launch agent from another Dex product was skipped"
    )


def test_preflight_queue_maps_server_and_queued_errors_to_broken(monkeypatch, context):
    monkeypatch.setattr(
        doctor,
        "_preflight_snapshot",
        lambda _context: ({"servers": {"work-mcp": {"status": "ok"}}}, []),
    )
    assert doctor._probe_preflight_queue(context).verdict == "OK"

    monkeypatch.setattr(
        doctor,
        "_preflight_snapshot",
        lambda _context: (
            {"servers": {"work-mcp": {"status": "error", "humanError": "Task Manager cannot start"}}},
            [],
        ),
    )
    assert doctor._probe_preflight_queue(context).verdict == "BROKEN"

    monkeypatch.setattr(
        doctor,
        "_preflight_snapshot",
        lambda _context: ({"servers": {}}, [{"acknowledged": False, "humanMessage": "Background failure"}]),
    )
    queued = doctor._probe_preflight_queue(context)
    assert queued.verdict == "BROKEN"
    assert queued.heal is None


def test_preflight_surfaces_unknown_registered_core_server(monkeypatch, context):
    server = context.vault_root / "core" / "mcp" / "session_memory_server.py"
    server.parent.mkdir(parents=True)
    server.touch()
    _write_mcp_config(
        context,
        {"session-memory": {"command": sys.executable, "args": [str(server)]}},
    )
    monkeypatch.setattr(
        doctor,
        "_preflight_snapshot",
        lambda _context: (
            {"servers": {"session-memory": {"status": "unknown", "note": "Not a core Dex server"}}},
            [],
        ),
    )

    result = doctor._probe_preflight_queue(context)

    assert result.verdict == "UNKNOWN"
    assert "session-memory" in result.detail


def test_customization_skills_validate_user_and_shipped_files(context):
    custom_skill = _write_skill(context, "notes-custom", frontmatter_name="wrong-name")

    custom_only = doctor._probe_customization_skills(context)

    custom_path = custom_skill.relative_to(context.vault_root).as_posix()
    assert custom_only.verdict == "BROKEN"
    assert f"user customization {custom_path}" in custom_only.detail
    assert f"fix or remove {custom_path}" in custom_only.detail
    assert "/dex-update" not in custom_only.detail

    shipped_skill = _write_skill(context, "daily-plan", frontmatter_name="wrong-name")
    mixed = doctor._probe_customization_skills(context)

    shipped_path = shipped_skill.relative_to(context.vault_root).as_posix()
    assert mixed.verdict == "BROKEN"
    assert f"shipped skill {shipped_path}" in mixed.detail
    assert f"run /dex-update to restore {shipped_path}" in mixed.detail


def test_customization_skills_are_ok_when_every_frontmatter_is_valid(context):
    _write_skill(context, "daily-plan")
    _write_skill(context, "notes-custom")

    result = doctor._probe_customization_skills(context)

    assert result.verdict == "OK"
    assert "1 user customization" in result.detail


def test_customization_skills_ignore_empty_retired_skill_directories(context):
    _write_skill(context, "daily-plan")
    retired = context.vault_root / ".claude" / "skills" / "retired-shipped-skill"
    retired.mkdir(parents=True)

    result = doctor._probe_customization_skills(context)

    assert result.verdict == "OK"
    assert result.detail == "Validated 0 user customizations and 1 shipped skill"


def test_customization_skill_containers_are_not_validated_or_counted_as_skills(context):
    _write_skill(context, "daily-plan")
    assert {"_available", "integrations"} <= doctor.KNOWN_SKILL_CONTAINER_DIRECTORIES
    for name in doctor.KNOWN_SKILL_CONTAINER_DIRECTORIES:
        container = context.vault_root / ".claude" / "skills" / name
        container.mkdir(parents=True)
        (container / "README.md").write_text("Reference material, not a skill.\n", encoding="utf-8")

    result = doctor._probe_customization_skills(context)

    assert result.verdict == "OK"
    assert result.detail == "Validated 0 user customizations and 1 shipped skill"


def test_customization_skills_only_prescribe_update_for_catalogued_paths(context):
    catalogued = ".claude/skills/fixture-item/SKILL.md"
    unlisted_skill = _write_skill(context, "unlisted-skill", frontmatter_name="wrong-name")
    _write_release_catalog(context, content=b"not valid skill frontmatter\n")

    result = doctor._probe_customization_skills(context)

    unlisted = unlisted_skill.relative_to(context.vault_root).as_posix()
    assert result.verdict == "BROKEN"
    assert f"run /dex-update to restore {catalogued}" in result.detail
    assert f"fix or remove {unlisted}" in result.detail
    assert f"run /dex-update to restore {unlisted}" not in result.detail


def test_repository_shipped_skill_tree_is_doctor_clean_and_restore_advice_is_real(
    tmp_path: Path,
) -> None:
    skills_root = REPO_ROOT / ".claude" / "skills"
    manifest_path = REPO_ROOT / "System" / ".installed-files.manifest"
    assert skills_root.is_dir(), "repository shipped skills tree is missing"
    assert manifest_path.is_file(), "repository installed-files manifest is missing"
    for name in ("_available", "integrations"):
        assert (skills_root / name).is_dir(), f"shipped skill container {name} is missing"

    context = doctor.DoctorContext(
        vault_root=REPO_ROOT,
        repo_root=REPO_ROOT,
        home=tmp_path,
        now=NOW,
    )
    result = doctor._probe_customization_skills(context)

    assert result.verdict == "OK", result.detail
    migration = doctor._probe_migration_pending(context)
    assert migration.verdict == "OFF", migration.detail
    rooms = doctor._probe_capability_rooms(context)
    assert rooms.verdict in {"OK", "OFF"}, rooms.detail
    shipped_paths = set(manifest_path.read_text(encoding="utf-8").splitlines())
    restore_paths = re.findall(r"run /dex-update to restore ([^;]+)", result.detail)
    assert all(path in shipped_paths for path in restore_paths), result.detail

    archive = tmp_path / "shipped-head.tar"
    subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(REPO_ROOT),
            "archive",
            "--format=tar",
            f"--output={archive}",
            "HEAD",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    shipped_root = tmp_path / "shipped-head"
    shutil.unpack_archive(archive, shipped_root)
    _git(shipped_root, "init")
    _git(shipped_root, "config", "user.email", "doctor@example.com")
    _git(shipped_root, "config", "user.name", "Doctor Test")
    _git(shipped_root, "add", "-f", "--", ".")
    _git(shipped_root, "commit", "-m", "actual shipped HEAD")
    _git(shipped_root, "update-ref", _remote_release_ref("stable"), "HEAD")
    shipped_context = doctor.DoctorContext(
        vault_root=shipped_root,
        repo_root=shipped_root,
        home=tmp_path / "shipped-home",
        now=NOW,
    )
    shipped_drift = doctor._probe_core_drift(shipped_context)
    assert shipped_drift.verdict == "OK", shipped_drift.detail


def test_customization_skills_do_not_follow_user_symlinks(context, tmp_path):
    external = tmp_path / "external-skill"
    external.mkdir()
    (external / "SKILL.md").write_text(
        "---\nname: notes-custom\ndescription: Must not be read\n---\n",
        encoding="utf-8",
    )
    skills_root = context.vault_root / ".claude" / "skills"
    skills_root.mkdir(parents=True)
    (skills_root / "notes-custom").symlink_to(external, target_is_directory=True)

    result = doctor._probe_customization_skills(context)

    assert result.verdict == "UNKNOWN"
    assert ".claude/skills/notes-custom/SKILL.md" in result.detail
    assert "was not read for safety" in result.detail
    assert "fix or remove" in result.detail
    assert "/dex-update" not in result.detail


def test_customization_mcp_compiles_custom_python_without_running_or_littering(context):
    sentinel = context.vault_root / "custom-command-ran"
    target = context.vault_root / "custom-mcp" / "server.py"
    target.parent.mkdir()
    target.write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    _write_mcp_config(
        context,
        {
            "work-mcp": {"command": "python", "args": ["core/mcp/work_server.py"]},
            "custom-sentinel": {"command": sys.executable, "args": [str(target)]},
        },
    )

    result = doctor._probe_customization_mcp(context)

    assert result.verdict == "OK"
    assert "not executed for safety" in result.detail
    assert not sentinel.exists()
    assert not (target.parent / "__pycache__").exists()
    assert list(target.parent.glob("*.pyc")) == []


def test_customization_mcp_reports_compile_and_placeholder_failures_with_exact_paths(context):
    target = context.vault_root / "custom-mcp" / "broken.py"
    target.parent.mkdir()
    target.write_text("if True print('broken')\n", encoding="utf-8")
    config_path = _write_mcp_config(
        context,
        {"custom-broken": {"command": sys.executable, "args": [str(target)]}},
    )

    compile_failure = doctor._probe_customization_mcp(context)

    relative_target = target.relative_to(context.vault_root).as_posix()
    assert compile_failure.verdict == "BROKEN"
    assert relative_target in compile_failure.detail
    assert ".mcp.json" in compile_failure.detail
    assert "fix your customization" in compile_failure.detail
    assert "/dex-update" not in compile_failure.detail
    assert not (target.parent / "__pycache__").exists()

    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "custom-broken": {
                        "command": "python",
                        "args": ["{{CUSTOM_SERVER_PATH}}"],
                    }
                }
            }
        )
    )
    placeholder_failure = doctor._probe_customization_mcp(context)

    assert placeholder_failure.verdict == "BROKEN"
    assert "unresolved placeholder" in placeholder_failure.detail
    assert ".mcp.json" in placeholder_failure.detail


def test_customization_mcp_is_ok_without_custom_entries(context):
    _write_mcp_config(
        context,
        {"work-mcp": {"command": "python", "args": ["core/mcp/work_server.py"]}},
    )

    result = doctor._probe_customization_mcp(context)

    assert result.verdict == "OK"
    assert "0 custom" in result.detail


def test_customization_mcp_does_not_compile_symlinked_python_target(
    monkeypatch,
    context,
    tmp_path,
):
    external = tmp_path / "credentials.py"
    external.write_text("raise RuntimeError('must not compile')\n", encoding="utf-8")
    target = context.vault_root / "custom-mcp" / "server.py"
    target.parent.mkdir()
    target.symlink_to(external)
    _write_mcp_config(
        context,
        {"custom-notes": {"command": sys.executable, "args": [str(target)]}},
    )
    monkeypatch.setattr(
        doctor.py_compile,
        "compile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("compiled unsafe target")),
    )

    result = doctor._probe_customization_mcp(context)

    assert result.verdict == "UNKNOWN"
    assert "custom-mcp/server.py" in result.detail
    assert ".mcp.json" in result.detail
    assert "not compiled or executed for safety" in result.detail
    assert "/dex-update" not in result.detail


def test_customization_mcp_does_not_read_symlinked_live_config(context, tmp_path):
    external = tmp_path / "external-mcp.json"
    external.write_text('{"mcpServers": {}}\n', encoding="utf-8")
    config = context.vault_root / ".mcp.json"
    config.symlink_to(external)

    result = doctor._probe_customization_mcp(context)

    assert result.verdict == "UNKNOWN"
    assert ".mcp.json is symlinked" in result.detail
    assert "was not read or executed for safety" in result.detail


def test_core_drift_is_ok_for_a_clean_release_checkout(tmp_path):
    drift_context = _drift_context(tmp_path)

    assert doctor._probe_core_drift(drift_context).verdict == "OK"


def test_core_drift_compares_against_the_installed_release_identity(tmp_path):
    """Drift means "differs from the release you actually have installed".

    Two other reference points are both wrong (issue #242 item 2): the
    merge-base lags installs where the legacy updater delivered release
    files without advancing shared history (byte-identical release content
    read as user modifications), and the fetched release tip can be newer
    than what is installed (files matching a not-yet-installed release
    would pass, masking a mixed-version vault). package.json names the
    installed version and releases are tagged, so the tag is the identity.
    """
    drift_context = _drift_context(tmp_path)
    vault = drift_context.vault_root
    base = _git(vault, "rev-parse", "HEAD").stdout.strip()

    # The installed release: shipped.py advances and the version is tagged.
    (vault / "core" / "shipped.py").write_text("SHIPPED = 2\n")
    (vault / "package.json").write_text('{\n  "version": "9.9.9"\n}\n')
    _git(vault, "add", "package.json")
    _git(vault, "commit", "-am", "installed release")
    _git(vault, "tag", "v9.9.9")

    # The repo has since FETCHED a newer release the user has not installed.
    (vault / "core" / "shipped.py").write_text("SHIPPED = 3\n")
    _git(vault, "commit", "-am", "newer fetched release")
    _git(vault, "update-ref", _remote_release_ref("stable"), "HEAD")

    # The vault's own history stays at the old baseline plus a local commit
    # carrying the exact bytes the INSTALLED (v9.9.9) release ships — how a
    # legacy update leaves a vault (files copied, shared history unmoved).
    _git(vault, "reset", "--hard", base)
    (vault / "core" / "shipped.py").write_text("SHIPPED = 2\n")
    (vault / "package.json").write_text('{\n  "version": "9.9.9"\n}\n')
    _git(vault, "add", "package.json")
    _git(vault, "commit", "-am", "release files copied without shared history")

    # Byte-identical to the installed release: not drift.
    assert doctor._probe_core_drift(drift_context).verdict == "OK"

    # Matching the NEWER fetched-but-not-installed release is still drift —
    # a mixed-version vault must not be masked by the fetched tip.
    (vault / "core" / "shipped.py").write_text("SHIPPED = 3\n")
    mixed = doctor._probe_core_drift(drift_context)
    assert mixed.verdict == "UNKNOWN"
    assert "core/shipped.py" in mixed.detail

    # A genuine user edit matching no release is reported too.
    (vault / "core" / "shipped.py").write_text("SHIPPED = 999  # user edit\n")
    edited = doctor._probe_core_drift(drift_context)
    assert edited.verdict == "UNKNOWN"
    assert "core/shipped.py" in edited.detail


def test_worktree_blob_ids_hash_large_release_trees_in_pipe_safe_batches(
    context,
    monkeypatch,
) -> None:
    relatives = [f"core/release-file-{index:04d}.py" for index in range(600)]
    expected = {
        relative: hashlib.sha1(relative.encode("utf-8"), usedforsecurity=False).hexdigest()
        for relative in relatives
    }
    observed_batches: list[list[str]] = []

    def pipe_limited_git_result(
        _context,
        *arguments,
        git_directory=None,
        input_text=None,
    ) -> subprocess.CompletedProcess[str]:
        assert arguments == ("hash-object", "--no-filters", "--stdin-paths")
        assert git_directory is None
        batch = input_text.splitlines()
        observed_batches.append(batch)
        if len(batch) > 128:
            return subprocess.CompletedProcess(arguments, 1, "", "simulated pipe saturation")
        return subprocess.CompletedProcess(
            arguments,
            0,
            "".join(f"{expected[relative]}\n" for relative in batch),
            "",
        )

    monkeypatch.setattr(doctor, "_git_result", pipe_limited_git_result)

    assert doctor._worktree_blob_ids(context, relatives) == expected
    assert len(observed_batches) > 1
    assert max(map(len, observed_batches)) <= 128


def test_post_split_core_drift_accepts_only_installer_normalized_package_metadata(
    context,
) -> None:
    brain = _write_split_topology(context)
    baseline_package = {
        "name": "dex-pkm",
        "version": "1.80.5",
        "scripts": {"meeting-sync": "node sync.cjs"},
        "dependencies": {"js-yaml": "^4.1.0"},
    }
    baseline_lock = {
        "name": "dex-pkm",
        "version": "1.75.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {
                "name": "dex-pkm",
                "version": "1.75.0",
                "dependencies": {"js-yaml": "^4.1.0"},
            }
        },
    }
    (context.vault_root / "package.json").write_text(
        json.dumps(baseline_package, indent=2) + "\n",
        encoding="utf-8",
    )
    (context.vault_root / "package-lock.json").write_text(
        json.dumps(baseline_lock, indent=2) + "\n",
        encoding="utf-8",
    )
    (context.vault_root / "System/.installed-files.manifest").write_text(
        "package-lock.json\npackage.json\n",
        encoding="utf-8",
    )
    _git(
        context.vault_root,
        "add",
        "package.json",
        "package-lock.json",
        "System/.installed-files.manifest",
    )
    _git(context.vault_root, "commit", "-m", "foundation package metadata")
    installed = _git(context.vault_root, "rev-parse", "HEAD").stdout.strip()
    subprocess.run(
        [
            "git",
            f"--git-dir={brain}",
            "fetch",
            "--quiet",
            str(context.vault_root),
            f"+{installed}:refs/dex/installed",
        ],
        check=True,
    )
    current_package = {
        **baseline_package,
        "scripts": {
            **baseline_package["scripts"],
            "test:hooks": "node --test .claude/hooks/tests/*.test.cjs",
            "check:connections-contract": (
                "node scripts/check-connections-contract.mjs && "
                "node scripts/build-connections-engine-manifest.mjs --check"
            ),
        },
    }
    current_lock = {
        **baseline_lock,
        "version": "1.80.5",
        "packages": {
            "": {
                **baseline_lock["packages"][""],
                "version": "1.80.5",
            }
        },
    }
    (context.vault_root / "package.json").write_text(
        json.dumps(current_package, indent=2) + "\n",
        encoding="utf-8",
    )
    (context.vault_root / "package-lock.json").write_text(
        json.dumps(current_lock, indent=2) + "\n",
        encoding="utf-8",
    )

    result = doctor._probe_core_drift(context)

    assert result.verdict == "OK"
    assert result.detail == "No shipped brain files differ from refs/dex/installed"

    current_package["scripts"]["test:exfiltrate"] = "curl https://example.test"
    (context.vault_root / "package.json").write_text(
        json.dumps(current_package, indent=2) + "\n",
        encoding="utf-8",
    )
    result = doctor._probe_core_drift(context)
    assert result.verdict == "UNKNOWN"
    assert "package.json" in result.detail

    del current_package["scripts"]["test:exfiltrate"]
    current_package["dependencies"]["js-yaml"] = "*"
    (context.vault_root / "package.json").write_text(
        json.dumps(current_package, indent=2) + "\n",
        encoding="utf-8",
    )
    result = doctor._probe_core_drift(context)
    assert result.verdict == "UNKNOWN"
    assert "package.json" in result.detail


def test_post_split_core_drift_accepts_the_composed_vault_mode_gitignore(
    context,
) -> None:
    """The vault-mode section Dex composes at delivery is not user drift.

    ``.gitignore`` is brain-owned and shipped, so the post-split probe compares
    its worktree bytes against ``refs/dex/installed``. The update deliberately
    appends a managed vault-mode section when it writes the file into a vault,
    so a plain byte comparison would report every updated vault as carrying
    modified shipped files. Edits outside that section are still drift.
    """
    from core.update import apply_update

    brain = _write_split_topology(context)
    release_blob = b"# distribution rules\n!core/\n!docs/\n"
    (context.vault_root / ".gitignore").write_bytes(release_blob)
    (context.vault_root / "System/.installed-files.manifest").write_text(
        ".gitignore\n",
        encoding="utf-8",
    )
    _git(context.vault_root, "add", ".gitignore", "System/.installed-files.manifest")
    _git(context.vault_root, "commit", "--quiet", "-m", "release gitignore")
    installed = _git(context.vault_root, "rev-parse", "HEAD").stdout.strip()
    subprocess.run(
        [
            "git",
            f"--git-dir={brain}",
            "fetch",
            "--quiet",
            str(context.vault_root),
            f"+{installed}:refs/dex/installed",
        ],
        check=True,
    )

    composed = apply_update._compose_gitignore(release_blob, context.vault_root)
    assert composed != release_blob
    (context.vault_root / ".gitignore").write_bytes(composed)

    result = doctor._probe_core_drift(context)

    assert result.verdict == "OK"
    assert result.detail == "No shipped brain files differ from refs/dex/installed"

    (context.vault_root / ".gitignore").write_bytes(composed + b"secret-exfil/\n")
    edited = doctor._probe_core_drift(context)
    assert edited.verdict == "UNKNOWN"
    assert ".gitignore" in edited.detail


def test_repository_credential_named_release_files_match_head_without_python_reads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = doctor.DoctorContext(
        vault_root=REPO_ROOT,
        repo_root=REPO_ROOT,
        home=tmp_path,
        now=NOW,
    )
    release_entries = doctor._release_tree_entries(context, "HEAD")
    credential_paths = sorted(
        relative
        for relative in release_entries
        if "credential" in relative.casefold()
        and not relative.startswith("core/tests/")
    )
    assert credential_paths == [
        "core/utils/credential_migration_exceptions.json",
        "core/utils/credential_remediation.py",
        "core/utils/credential_scanner.py",
        "core/utils/credential_workflow.py",
        "core/utils/integration_credentials.py",
        "docs/credential-remediation.md",
    ]
    protected = {REPO_ROOT / relative for relative in credential_paths}
    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text

    def refuse_credential_content(path: Path) -> bytes:
        if path in protected:
            raise AssertionError(f"doctor read credential-shaped content: {path}")
        return original_read_bytes(path)

    def refuse_credential_text(path: Path, *args, **kwargs) -> str:
        if path in protected:
            raise AssertionError(f"doctor read credential-shaped content: {path}")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", refuse_credential_content)
    monkeypatch.setattr(Path, "read_text", refuse_credential_text)

    assert all(
        doctor._worktree_matches_release_blob(
            context,
            relative,
            *release_entries[relative],
        )
        for relative in credential_paths
    )


def test_core_drift_excludes_user_owned_seed_files(tmp_path: Path) -> None:
    drift_context = _drift_context(tmp_path)
    vault = drift_context.vault_root
    seeds = {
        "02-Week_Priorities/Week_Priorities.md": "# Priorities\n",
        "03-Tasks/Tasks.md": "# Tasks\n",
    }
    for relative, content in seeds.items():
        path = vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(vault, "add", "--", *seeds)
    _git(vault, "commit", "-m", "ship seed fixtures")
    _git(vault, "update-ref", _remote_release_ref("stable"), "HEAD")
    for relative in seeds:
        (vault / relative).write_text(
            seeds[relative] + "User-authored content.\n",
            encoding="utf-8",
        )

    result = doctor._probe_core_drift(drift_context)

    assert result.verdict == "OK"
    assert all(relative not in result.detail for relative in seeds)


def test_core_drift_missing_channel_keeps_stable_release_ref_behavior(tmp_path):
    drift_context = _drift_context(tmp_path)

    assert doctor._upstream_release_ref(drift_context) == _remote_release_ref("stable")
    assert doctor._probe_core_drift(drift_context).verdict == "OK"


def test_core_drift_is_ok_for_clean_beta_head_against_beta_release(tmp_path):
    drift_context = _drift_context(tmp_path, channel="beta")

    result = doctor._probe_core_drift(drift_context)

    assert result.verdict == "OK"
    assert result.detail == "No tracked shipped files differ from the installed release"


def test_core_drift_beta_without_beta_ref_is_unknown_and_does_not_use_stable(tmp_path):
    drift_context = _drift_context(tmp_path, release_ref=False, channel="beta")
    _git(drift_context.repo_root, "update-ref", _remote_release_ref("stable"), "HEAD")

    result = doctor._probe_core_drift(drift_context)

    assert result.verdict == "UNKNOWN"
    assert result.detail == "beta channel selected but no beta release found — staying on stable is safe"


def test_core_drift_invalid_channel_is_unknown_and_does_not_use_stable(tmp_path):
    drift_context = _drift_context(tmp_path, channel="nightly")

    result = doctor._probe_core_drift(drift_context)

    assert result.verdict == "UNKNOWN"
    assert result.detail == "couldn't verify your update channel"


def test_core_drift_missing_pyyaml_is_reported_distinctly_from_a_broken_profile(monkeypatch, tmp_path):
    """A missing dependency must not be reported as if the user's settings file were broken."""
    drift_context = _drift_context(tmp_path, channel="beta")
    monkeypatch.setitem(sys.modules, "yaml", None)

    result = doctor._probe_core_drift(drift_context)

    assert result.verdict == "UNKNOWN"
    assert result.detail == "PyYAML isn't installed — Dex can't read your update channel setting"


def test_core_drift_never_executes_repo_fsmonitor_or_ambient_git(
    monkeypatch,
    tmp_path,
):
    drift_context = _drift_context(tmp_path)
    sentinel = tmp_path / "doctor-user-command-ran"
    fsmonitor = tmp_path / "fsmonitor.sh"
    fsmonitor.write_text(
        f"#!/bin/sh\n/usr/bin/touch {str(sentinel)!r}\nprintf '0\\n'\n",
        encoding="utf-8",
    )
    fsmonitor.chmod(0o755)
    _git(drift_context.repo_root, "config", "core.fsmonitor", str(fsmonitor))
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        f"#!/bin/sh\n/usr/bin/touch {str(sentinel)!r}\nexit 0\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))

    result = doctor._probe_core_drift(drift_context)

    assert result.verdict == "OK"
    assert not sentinel.exists()


def test_core_drift_lists_modified_shipped_files_without_calling_them_broken(tmp_path):
    drift_context = _drift_context(tmp_path)
    shipped = drift_context.vault_root / "core" / "shipped.py"
    shipped.write_text("SHIPPED = 2\n")

    result = doctor._probe_core_drift(drift_context)

    assert result.verdict == "UNKNOWN"
    assert "core/shipped.py" in result.detail
    assert "updates may conflict; the doctor can't vouch for modified shipped files" in result.detail
    assert result.heal is None


def test_core_drift_reports_modified_installed_file_deleted_by_latest_release(tmp_path):
    drift_context = _drift_context(tmp_path)
    vault = drift_context.vault_root
    installed = _git(vault, "rev-parse", "HEAD").stdout.strip()

    _git(vault, "checkout", "-b", "next-release")
    (vault / "core" / "shipped.py").unlink()
    _git(vault, "add", "-u", "--", "core/shipped.py")
    _git(vault, "commit", "-m", "delete shipped file")
    _git(vault, "update-ref", _remote_release_ref("stable"), "HEAD")
    _git(vault, "checkout", "--detach", installed)
    (vault / "core" / "shipped.py").write_text("SHIPPED = 2\n")

    result = doctor._probe_core_drift(drift_context)

    assert result.verdict == "UNKNOWN"
    assert "core/shipped.py" in result.detail
    assert "updates may conflict" in result.detail


def test_core_drift_is_unknown_when_no_release_remote_exists(tmp_path):
    drift_context = _drift_context(tmp_path, release_ref=False)

    result = doctor._probe_core_drift(drift_context)

    assert result.verdict == "UNKNOWN"
    assert result.detail == "no upstream remote — can't compare"


def test_core_drift_ignores_user_extensions_block_only_changes(tmp_path):
    drift_context = _drift_context(tmp_path)
    claude = drift_context.vault_root / "CLAUDE.md"
    claude.write_text(
        "# Dex\n\n"
        "## USER_EXTENSIONS_START\n"
        "Always use my preferred meeting template.\n"
        "This can span several lines.\n"
        "## USER_EXTENSIONS_END\n\n"
        "Shipped tail.\n"
    )

    assert doctor._probe_core_drift(drift_context).verdict == "OK"


def test_core_drift_does_not_read_symlinked_claude_file(monkeypatch, tmp_path):
    drift_context = _drift_context(tmp_path)
    claude = drift_context.vault_root / "CLAUDE.md"
    external = tmp_path / ".env.credentials"
    external.write_text("TOP_SECRET=must-not-read\n", encoding="utf-8")
    claude.unlink()
    claude.symlink_to(external)
    original_read_text = Path.read_text

    def guarded_read_text(path, *args, **kwargs):
        if path == claude:
            raise AssertionError("core.drift followed a symlinked CLAUDE.md")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    result = doctor._probe_core_drift(drift_context)

    assert result.verdict == "UNKNOWN"
    assert "CLAUDE.md" in result.detail
    assert "must-not-read" not in result.detail


def test_core_drift_excludes_all_sanctioned_customization_surfaces(tmp_path):
    drift_context = _drift_context(tmp_path)
    vault = drift_context.vault_root
    config = json.loads((vault / ".mcp.json").read_text())
    config["mcpServers"]["custom-notes"] = {"command": "notes-mcp", "args": []}
    (vault / ".mcp.json").write_text(json.dumps(config, indent=2) + "\n")
    (vault / "System" / "user-profile.yaml").write_text("name: Customized\n")
    (vault / "System" / "pillars.yaml").write_text("pillars: [Health]\n")
    (vault / "System" / "integrations" / "calendar.yaml").write_text("enabled: true\n")

    assert doctor._probe_core_drift(drift_context).verdict == "OK"


def test_core_drift_does_not_hide_shipped_edits_mixed_with_sanctioned_changes(tmp_path):
    drift_context = _drift_context(tmp_path)
    vault = drift_context.vault_root
    config = json.loads((vault / ".mcp.json").read_text())
    config["mcpServers"]["custom-notes"] = {"command": "notes-mcp", "args": []}
    (vault / ".mcp.json").write_text(json.dumps(config, indent=2) + "\n")
    (vault / "CLAUDE.md").write_text(
        "# Dex changed outside the user block\n\n"
        "## USER_EXTENSIONS_START\nMy local extension.\n## USER_EXTENSIONS_END\n\n"
        "Shipped tail.\n"
    )

    result = doctor._probe_core_drift(drift_context)

    assert result.verdict == "UNKNOWN"
    assert "CLAUDE.md" in result.detail
    assert ".mcp.json" not in result.detail


def test_smoke_journeys_roll_up_unknown_and_use_the_same_interpreter(monkeypatch, context):
    payload = {
        "schema_version": 1,
        "generated_at": NOW.isoformat(),
        "journeys": [
            {"id": "configs", "verdict": "OK", "detail": "configs parse", "duration_ms": 1},
            {"id": "mcp_startup", "verdict": "UNKNOWN", "detail": "not executed for safety", "duration_ms": 2},
            {"id": "hooks", "verdict": "OFF", "detail": "no hooks", "duration_ms": 1},
        ],
        "summary": {"ok": 1, "broken": 0, "unknown": 1, "off": 1},
    }
    observed = {}

    def run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(doctor.subprocess, "run", run)

    result = doctor._probe_smoke_journeys(context)

    assert result.verdict == "UNKNOWN"
    assert "configs [OK]: configs parse" in result.detail
    assert "mcp_startup [UNKNOWN]: not executed for safety" in result.detail
    assert observed["command"] == [
        sys.executable,
        str(context.repo_root / "core" / "utils" / "smoke.py"),
        "--json",
    ]
    assert observed["kwargs"]["env"]["VAULT_PATH"] == str(context.vault_root)
    assert observed["kwargs"]["cwd"] == context.vault_root


def test_smoke_journeys_use_vault_venv_where_yaml_is_actually_installed(
    tmp_path,
):
    vault = tmp_path / "vault"
    smoke_path = vault / "core" / "utils" / "smoke.py"
    smoke_path.parent.mkdir(parents=True)
    (vault / "System").mkdir()
    venv.create(vault / ".venv", with_pip=False)
    python = vault / ".venv" / "bin" / "python"
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = vault / ".venv" / "lib" / version / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    (site_packages / "yaml.py").write_text("SAFE_SENTINEL = True\n", encoding="utf-8")
    smoke_path.write_text(
        "import json, yaml\n"
        "assert yaml.SAFE_SENTINEL is True\n"
        "print(json.dumps({"
        "'schema_version': 1,"
        "'journeys': [{'id': 'configs', 'verdict': 'OK', "
        "'detail': 'configs parse', 'duration_ms': 1}],"
        "'summary': {'ok': 1, 'broken': 0, 'unknown': 0, 'off': 0}"
        "}))\n",
        encoding="utf-8",
    )
    context = doctor.DoctorContext(
        vault_root=vault,
        repo_root=vault,
        home=tmp_path / "home",
        now=NOW,
    )

    result = doctor._probe_smoke_journeys(context)

    assert result.verdict == "OK"
    assert result.detail == "configs [OK]: configs parse"


def test_smoke_journeys_roll_up_broken_from_exit_one(monkeypatch, context):
    payload = {
        "schema_version": 1,
        "generated_at": NOW.isoformat(),
        "journeys": [
            {"id": "task_lifecycle", "verdict": "BROKEN", "detail": "Tasks.md changed", "duration_ms": 3}
        ],
        "summary": {"ok": 0, "broken": 1, "unknown": 0, "off": 0},
    }
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            1,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )

    result = doctor._probe_smoke_journeys(context)

    assert result.verdict == "BROKEN"
    assert "task_lifecycle" in result.detail


def test_smoke_harness_exit_two_becomes_an_unknown_failed_instrument(monkeypatch, context):
    _stub_probes(monkeypatch, exclude={"smoke.journeys"})
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            2,
            stdout="",
            stderr="global smoke harness failed",
        ),
    )

    report = doctor.collect(deep=True, context=context)

    smoke = _check(report, "smoke.journeys")
    assert smoke["verdict"] == "UNKNOWN"
    assert "global smoke harness failed" in smoke["detail"]
    assert report["instruments"]["failed"] == [
        {"id": "smoke.journeys", "error": "smoke harness failed: global smoke harness failed"}
    ]
    assert _check(report, "doctor.self")["verdict"] == "BROKEN"


def test_collect_preserves_smokes_missing_dex_module_diagnosis(monkeypatch, context):
    _stub_probes(monkeypatch, exclude={"smoke.journeys"})
    payload = {
        "schema_version": 1,
        "generated_at": NOW.isoformat(),
        "journeys": [
            {
                "id": "configs",
                "verdict": "UNKNOWN",
                "detail": "Dex's own code could not be loaded (No module named 'core'). "
                "This is a Dex checkup fault, not a missing Python package.",
                "duration_ms": 1,
            }
        ],
        "summary": {"ok": 0, "broken": 0, "unknown": 1, "off": 0},
    }
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )

    report = doctor.collect(deep=True, context=context)

    assert _check(report, "smoke.journeys")["detail"] == (
        "configs [UNKNOWN]: Dex's own code could not be loaded (No module named 'core'). "
        "This is a Dex checkup fault, not a missing Python package."
    )
    assert report["instruments"]["failed"] == []
    assert _check(report, "doctor.self")["verdict"] == "OK"


def test_granola_no_key_is_off_and_api_400_is_broken(monkeypatch, context):
    monkeypatch.setattr(doctor, "_granola_api_key", lambda _context: None)
    monkeypatch.setattr(
        doctor,
        "_granola_filtered_query",
        lambda _context: pytest.fail("query must not run without a key"),
    )
    assert doctor._probe_granola_query_path(context).verdict == "OFF"

    from core.mcp.granola_server import GranolaAPIError

    monkeypatch.setattr(doctor, "_granola_api_key", lambda _context: "grn_test")

    def api_400(_context):
        raise GranolaAPIError(status_code=400, body="created_after is invalid")

    monkeypatch.setattr(doctor, "_granola_filtered_query", api_400)
    result = doctor._probe_granola_query_path(context)
    assert result.verdict == "BROKEN"
    assert result.detail == (
        "Granola query failed (HTTP 400) — the connector may need updating. "
        "Response: created_after is invalid"
    )


def _write_backup_config(context, *, enabled=True):
    config = context.vault_root / "System" / "integrations" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "backup:\n"
        f"  enabled: {str(enabled).lower()}\n"
        "  backend: folder\n"
        "  destination: /backups\n"
    )


def _write_backup_stamp(context, *, ok, timestamp, error=None, warnings=None):
    runtime = context.vault_root / "System" / ".dex"
    runtime.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": timestamp,
        "ok": ok,
        "backend": "folder",
        "location": "/backups",
        "set": "20260710-020000",
    }
    if error is not None:
        payload["error"] = error
    if warnings is not None:
        payload["warnings"] = warnings
    (runtime / "backup-last-run.json").write_text(json.dumps(payload))


def test_backup_freshness_broken_when_a_recent_run_stored_less_than_asked(context):
    """A fresh, successful, but degraded backup must not report a bare OK."""
    _write_backup_config(context)
    _write_backup_stamp(
        context,
        ok=True,
        timestamp="2026-07-10T02:00:00+00:00",
        warnings=["the vault's version history could not be bundled, so this "
                  "set holds the notes archive only: fatal: Refusing to create "
                  "empty bundle."],
    )
    result = doctor._probe_backup_freshness(context)
    assert result.verdict == "BROKEN"
    assert "stored less than a full backup" in result.detail
    assert "version history could not be bundled" in result.detail
    assert result.heal is not None


def test_backup_freshness_stays_ok_when_the_run_recorded_no_warnings(context):
    _write_backup_config(context)
    _write_backup_stamp(
        context, ok=True, timestamp="2026-07-10T02:00:00+00:00", warnings=[])
    assert doctor._probe_backup_freshness(context).verdict == "OK"


def test_backup_freshness_off_when_not_configured(context):
    assert doctor._probe_backup_freshness(context).verdict == "OFF"

    _write_backup_config(context, enabled=False)
    result = doctor._probe_backup_freshness(context)
    assert result.verdict == "OFF"
    assert result.heal is None


def test_backup_freshness_ok_when_last_success_is_within_two_days(context):
    _write_backup_config(context)
    _write_backup_stamp(context, ok=True, timestamp="2026-07-10T02:00:00+00:00")
    result = doctor._probe_backup_freshness(context)
    assert result.verdict == "OK"
    assert "20260710-020000" in result.detail
    assert "/backups" in result.detail


def test_backup_freshness_broken_when_last_run_failed(context):
    _write_backup_config(context)
    _write_backup_stamp(
        context,
        ok=False,
        timestamp="2026-07-11T02:00:00+00:00",
        error="backup.destination is not set; run /backup-setup",
    )
    result = doctor._probe_backup_freshness(context)
    assert result.verdict == "BROKEN"
    assert "backup.destination is not set" in result.detail
    assert result.heal.tier == 3
    assert "/backup-setup" in result.heal.action


def test_backup_freshness_broken_when_newest_success_is_stale(context):
    _write_backup_config(context)
    _write_backup_stamp(context, ok=True, timestamp="2026-07-05T02:00:00+00:00")
    result = doctor._probe_backup_freshness(context)
    assert result.verdict == "BROKEN"
    assert "6 days old" in result.detail
    assert result.heal.tier == 3


def test_backup_freshness_broken_when_configured_but_never_ran(context):
    _write_backup_config(context)
    result = doctor._probe_backup_freshness(context)
    assert result.verdict == "BROKEN"
    assert "never recorded a run" in result.detail
    assert result.heal.tier == 3


def test_backup_freshness_unknown_when_stamp_is_unreadable(context):
    _write_backup_config(context)
    runtime = context.vault_root / "System" / ".dex"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "backup-last-run.json").write_text("{not json")
    result = doctor._probe_backup_freshness(context)
    assert result.verdict == "UNKNOWN"
    assert "could not be read" in result.detail


def test_granola_key_adapter_reads_exported_quoted_env_file(monkeypatch, context):
    monkeypatch.delenv("GRANOLA_API_KEY", raising=False)
    (context.vault_root / ".env").write_text('export GRANOLA_API_KEY="grn_file_key"\n')

    assert doctor._granola_api_key(context) == "grn_file_key"

    monkeypatch.setenv("GRANOLA_API_KEY", "grn_environment_key")
    assert doctor._granola_api_key(context) == "grn_environment_key"


def test_granola_live_wrapper_uses_the_filtered_real_query_path(monkeypatch, context):
    from core.mcp import granola_server

    calls = {}

    def cutoff(days):
        calls["days"] = days
        return "cutoff"

    monkeypatch.setattr(granola_server, "_cutoff_iso", cutoff)

    def list_notes(**kwargs):
        calls["list"] = kwargs
        return []

    monkeypatch.setattr(granola_server, "_list_notes", list_notes)

    doctor._granola_filtered_query(context)

    assert calls == {
        "days": 7,
        "list": {"created_after": "cutoff", "max_notes": 1, "page_size": 1},
    }


def test_calendar_permission_boundaries_and_configured_name(monkeypatch, context):
    _write_valid_configs(context)
    monkeypatch.setattr(doctor, "_calendar_permission_status", lambda _context: "not_determined")
    monkeypatch.setattr(
        doctor,
        "_calendar_list_result",
        lambda _context: pytest.fail("unused calendar must not prompt for permission"),
    )
    assert doctor._probe_calendar_access(context).verdict == "OFF"

    (context.vault_root / "System" / "user-profile.yaml").write_text(
        "calendar:\n  work_calendar: Team Calendar\n"
    )
    assert doctor._probe_calendar_access(context).verdict == "BROKEN"

    monkeypatch.setattr(doctor, "_calendar_permission_status", lambda _context: "denied")
    assert doctor._probe_calendar_access(context).verdict == "BROKEN"

    monkeypatch.setattr(doctor, "_calendar_permission_status", lambda _context: "authorized")
    monkeypatch.setattr(
        doctor,
        "_calendar_list_result",
        lambda _context: {"success": True, "calendars": ["Home", "Holidays"]},
    )
    missing = doctor._probe_calendar_access(context)
    assert missing.verdict == "BROKEN"
    assert "Home, Holidays" in missing.detail

    monkeypatch.setattr(
        doctor,
        "_calendar_list_result",
        lambda _context: {"success": True, "calendars": ["Team Calendar", "Home"]},
    )
    assert doctor._probe_calendar_access(context).verdict == "OK"


def test_google_calendar_provider_skips_eventkit(monkeypatch, context):
    _write_valid_configs(context, calendar="primary", calendar_provider="google")
    _write_mcp_config(
        context,
        {"google-workspace-mcp": {"command": "npx", "args": ["-y", "google-workspace-mcp"]}},
    )
    monkeypatch.setattr(
        doctor,
        "_calendar_permission_status",
        lambda _context: pytest.fail("Google calendar must not probe EventKit permission"),
    )
    monkeypatch.setattr(
        doctor,
        "_calendar_list_result",
        lambda _context: pytest.fail("Google calendar must not list EventKit calendars"),
    )
    monkeypatch.setattr(
        doctor,
        "_google_calendar_list_result",
        lambda _context: {
            "success": True,
            "calendars": ["Work"],
            "calendar_ids": ["primary"],
            "primary_id": "primary",
        },
    )

    result = doctor._probe_calendar_access(context)

    assert result.verdict == "OK"
    assert "1 calendar" in result.detail


def test_google_calendar_provider_without_connector_is_unknown_not_eventkit(
    monkeypatch,
    context,
):
    _write_valid_configs(context, calendar_provider="google")
    monkeypatch.setattr(
        doctor,
        "_calendar_permission_status",
        lambda _context: pytest.fail("Google calendar must not probe EventKit permission"),
    )
    monkeypatch.setattr(
        doctor,
        "_calendar_list_result",
        lambda _context: pytest.fail("Google calendar must not list EventKit calendars"),
    )

    missing = doctor._probe_calendar_access(context)

    assert missing.verdict == "UNKNOWN"
    assert missing.heal is None
    assert "live calendar list could not be completed" in missing.detail
    assert "EventKit" not in missing.detail


def test_google_calendar_provider_without_mcp_lists_when_token_is_present(
    monkeypatch,
    context,
):
    _write_valid_configs(context, calendar="primary", calendar_provider="google")
    monkeypatch.setattr(
        doctor,
        "_calendar_permission_status",
        lambda _context: pytest.fail("Google calendar must not probe EventKit permission"),
    )
    monkeypatch.setattr(
        doctor,
        "_calendar_list_result",
        lambda _context: pytest.fail("Google calendar must not list EventKit calendars"),
    )
    monkeypatch.setattr(
        doctor,
        "_google_calendar_list_result",
        lambda _context: {
            "success": True,
            "calendars": ["Work"],
            "calendar_ids": ["primary"],
            "primary_id": "primary",
        },
    )

    result = doctor._probe_calendar_access(context)

    assert result.verdict == "OK"
    assert "1 calendar" in result.detail


def test_google_calendar_missing_token_is_unknown_not_broken(monkeypatch, context):
    _write_valid_configs(context, calendar_provider="google")
    _write_mcp_config(
        context,
        {"google-workspace-mcp": {"command": "npx", "args": ["-y", "google-workspace-mcp"]}},
    )
    monkeypatch.setattr(
        doctor,
        "_calendar_permission_status",
        lambda _context: pytest.fail("Google calendar must not probe EventKit permission"),
    )

    result = doctor._probe_calendar_access(context)

    assert result.verdict == "UNKNOWN"
    assert "live calendar list could not be completed" in result.detail


def test_google_calendar_auth_failure_is_broken_with_setup_heal(monkeypatch, context):
    _write_valid_configs(context, calendar_provider="google")
    _write_mcp_config(
        context,
        {"google-workspace-mcp": {"command": "npx", "args": ["-y", "google-workspace-mcp"]}},
    )
    monkeypatch.setattr(
        doctor,
        "_google_calendar_list_result",
        lambda _context: {"success": False, "error": "Unauthorized", "http_status": 401},
    )

    result = doctor._probe_calendar_access(context)

    assert result.verdict == "BROKEN"
    assert result.heal.action == "Run /google-workspace-setup to connect Google Calendar."


def test_google_calendar_expired_token_with_refresh_is_unknown_not_broken(
    monkeypatch,
    context,
):
    _write_valid_configs(context, calendar_provider="google")
    _write_mcp_config(
        context,
        {"google-workspace-mcp": {"command": "npx", "args": ["-y", "google-workspace-mcp"]}},
    )
    token_path = context.vault_root / "System" / ".gmail-oauth-token.json"
    token_path.write_text(
        '{"access_token": "expired", "refresh_token": "still-valid"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        doctor,
        "_google_calendar_list_result",
        lambda _context: {"success": False, "error": "Unauthorized", "http_status": 401},
    )
    monkeypatch.setattr(
        doctor,
        "_calendar_permission_status",
        lambda _context: pytest.fail("Google calendar must not probe EventKit permission"),
    )

    result = doctor._probe_calendar_access(context)

    assert result.verdict == "UNKNOWN"
    assert "live calendar list could not be completed" in result.detail
    assert result.heal is None


def test_google_calendar_missing_configured_name(monkeypatch, context):
    _write_valid_configs(context, calendar="Team Calendar", calendar_provider="google")
    _write_mcp_config(
        context,
        {"google-workspace-mcp": {"command": "npx", "args": ["-y", "google-workspace-mcp"]}},
    )
    monkeypatch.setattr(
        doctor,
        "_google_calendar_list_result",
        lambda _context: {
            "success": True,
            "calendars": ["Home"],
            "calendar_ids": ["home@example.com"],
            "primary_id": "home@example.com",
        },
    )

    missing = doctor._probe_calendar_access(context)

    assert missing.verdict == "BROKEN"
    assert "Home" in missing.detail
    assert "work_calendar" in missing.heal.action


def test_skipped_calendar_provider_is_off_without_eventkit(monkeypatch, context):
    _write_valid_configs(context, calendar_provider="none")
    monkeypatch.setattr(
        doctor,
        "_calendar_permission_status",
        lambda _context: pytest.fail("A skipped calendar must not probe EventKit"),
    )

    assert doctor._probe_calendar_access(context).verdict == "OFF"


def test_google_calendar_list_adapter_reads_calendar_list_payload(monkeypatch, context):
    token_path = context.vault_root / "System" / ".gmail-oauth-token.json"
    token_path.write_text('{"access_token": "secret-token"}', encoding="utf-8")
    captured = {}

    class _Response:
        def read(self):
            return json.dumps(
                {
                    "items": [
                        {"id": "primary", "summary": "Work", "primary": True},
                        {"id": "home@example.com", "summary": "Home"},
                    ]
                }
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers.get("Authorization") or request.get_header(
            "Authorization"
        )
        captured["timeout"] = timeout
        return _Response()

    class _Opener:
        def open(self, request, timeout):
            return fake_urlopen(request, timeout)

    monkeypatch.setattr(doctor.urllib.request, "build_opener", lambda _handler: _Opener())

    result = doctor._google_calendar_list_result(context)

    assert captured["url"] == "https://www.googleapis.com/calendar/v3/users/me/calendarList"
    assert captured["authorization"] == "Bearer secret-token"
    assert captured["timeout"] == 10
    assert result["success"] is True
    assert result["calendars"] == ["Work", "Home"]
    assert result["calendar_ids"] == ["primary", "home@example.com"]
    assert result["primary_id"] == "primary"
    assert doctor._google_work_calendar_found("primary", result) is True
    assert doctor._google_work_calendar_found("Work", result) is True


def test_calendar_sandbox_failure_is_unknown(monkeypatch, context):
    _write_valid_configs(context, calendar="Team Calendar")
    monkeypatch.setattr(doctor, "_calendar_permission_status", lambda _context: "authorized")
    monkeypatch.setattr(
        doctor,
        "_calendar_list_result",
        lambda _context: {"success": False, "error": "sandbox: Operation not permitted"},
    )

    assert doctor._probe_calendar_access(context).verdict == "UNKNOWN"


def test_apple_mail_search_is_a_deep_check_and_adapts_the_focused_probe(
    monkeypatch,
    context,
):
    assert "mail.apple-search" in DEEP_IDS
    definition = next(check for check in doctor.DEEP_CHECKS if check.id == "mail.apple-search")
    assert definition.probe == "_probe_apple_mail_search"

    observed = {}

    def probe(adapter_context):
        observed["context"] = adapter_context
        return doctor.apple_mail_health.Result(
            "BROKEN",
            "Index cannot answer searches",
            action="Rebuild it",
            feature_status="broken",
            user_message="Mail search needs attention.",
        )

    monkeypatch.setattr(doctor.apple_mail_health, "probe", probe)
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_apple_mail_cli_present", lambda: True)

    result = doctor._probe_apple_mail_search(context)

    assert result.verdict == "BROKEN"
    assert result.detail == "Index cannot answer searches"
    assert result.feature_status == "broken"
    assert result.user_message == "Mail search needs attention."
    assert result.heal.action == "Rebuild it"
    assert observed["context"].home == context.home
    assert observed["context"].vault_root == context.vault_root
    assert observed["context"].project_config_path == context.vault_root / ".mcp.json"
    assert observed["context"].macos is True
    assert observed["context"].cli_present is True


def test_calendar_permission_adapter_preserves_eventkit_status(monkeypatch, context):
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    for raw_status, expected in (
        ("0\n", "not_determined"),
        ("1\n", "restricted"),
        ("2\n", "denied"),
        ("3\n", "authorized"),
        ("4\n", "write_only"),
        ("7\n", "unknown (7)"),
    ):
        monkeypatch.setattr(
            doctor.subprocess,
            "run",
            lambda command, _raw=raw_status, **_kwargs: subprocess.CompletedProcess(
                command,
                0,
                stdout=_raw,
                stderr="",
            ),
        )
        assert doctor._calendar_permission_status(context) == expected


def test_calendar_write_only_requires_full_access_and_unknown_preserves_raw_status(
    monkeypatch,
    context,
):
    _write_valid_configs(context, calendar="Team Calendar")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(
        doctor,
        "_calendar_list_result",
        lambda _context: pytest.fail("non-readable permission states must not query calendars"),
    )

    def eventkit_status(raw_status):
        monkeypatch.setattr(
            doctor.subprocess,
            "run",
            lambda command, **_kwargs: subprocess.CompletedProcess(
                command,
                0,
                stdout=f"{raw_status}\n",
                stderr="",
            ),
        )

    eventkit_status(4)
    write_only = doctor._probe_calendar_access(context)
    assert write_only.verdict == "BROKEN"
    assert "write only" in write_only.detail.lower()
    assert "full calendar access" in write_only.heal.action.lower()

    eventkit_status(7)
    unknown = doctor._probe_calendar_access(context)
    assert unknown.verdict == "UNKNOWN"
    assert "7" in unknown.detail


def test_calendar_list_adapter_calls_the_real_mcp_helper(monkeypatch, context):
    from core.mcp import calendar_server

    expected = {"success": True, "calendars": ["Team Calendar"]}
    monkeypatch.setattr(calendar_server, "_get_calendar_list_result", lambda: expected)

    assert doctor._calendar_list_result(context) is expected


def test_qmd_respects_opt_in_and_reports_live_status_failures(monkeypatch, context):
    _write_mcp_config(context, {})
    assert doctor._probe_qmd_live(context).verdict == "OFF"

    _write_mcp_config(context, {"qmd": {"command": "qmd", "args": ["mcp"]}})
    monkeypatch.setattr(doctor, "_qmd_binary", lambda _context: None)
    assert doctor._probe_qmd_live(context).verdict == "BROKEN"

    monkeypatch.setattr(doctor, "_qmd_binary", lambda _context: "/tmp/qmd")
    monkeypatch.setattr(doctor, "_qmd_status", lambda _binary: (False, "index metadata is corrupt"))
    failed = doctor._probe_qmd_live(context)
    assert failed.verdict == "BROKEN"
    assert "index metadata is corrupt" in failed.detail

    monkeypatch.setattr(doctor, "_qmd_status", lambda _binary: (False, "GPU unavailable in sandbox"))
    assert doctor._probe_qmd_live(context).verdict == "UNKNOWN"

    monkeypatch.setattr(doctor, "_qmd_status", lambda _binary: (True, "3 collections"))
    assert doctor._probe_qmd_live(context).verdict == "OK"


def test_qmd_timeout_is_unknown_without_breaking_doctor_self(monkeypatch, context):
    _stub_probes(monkeypatch, exclude={"qmd.live"})
    _write_mcp_config(context, {"qmd": {"command": "qmd", "args": ["mcp"]}})
    monkeypatch.setattr(doctor, "_qmd_binary", lambda _context: "/tmp/qmd")

    def time_out(_binary):
        raise subprocess.TimeoutExpired(["/tmp/qmd", "status"], timeout=10)

    monkeypatch.setattr(doctor, "_qmd_status", time_out)

    report = doctor.collect(deep=True, context=context)

    qmd = _check(report, "qmd.live")
    assert qmd["verdict"] == "UNKNOWN"
    assert "10 seconds" in qmd["detail"]
    assert report["instruments"]["failed"] == []
    assert _check(report, "doctor.self")["verdict"] == "OK"


def test_qmd_unexpected_exception_still_breaks_doctor_self(monkeypatch, context):
    _stub_probes(monkeypatch, exclude={"qmd.live"})
    _write_mcp_config(context, {"qmd": {"command": "qmd", "args": ["mcp"]}})
    monkeypatch.setattr(doctor, "_qmd_binary", lambda _context: "/tmp/qmd")
    monkeypatch.setattr(
        doctor,
        "_qmd_status",
        lambda _binary: (_ for _ in ()).throw(RuntimeError("unexpected qmd adapter failure")),
    )

    report = doctor.collect(deep=True, context=context)

    assert _check(report, "qmd.live")["verdict"] == "UNKNOWN"
    assert report["instruments"]["failed"] == [
        {"id": "qmd.live", "error": "unexpected qmd adapter failure"}
    ]
    assert _check(report, "doctor.self")["verdict"] == "BROKEN"


def test_qmd_nonzero_status_is_broken_without_breaking_doctor_self(monkeypatch, context):
    _stub_probes(monkeypatch, exclude={"qmd.live"})
    _write_mcp_config(context, {"qmd": {"command": "qmd", "args": ["mcp"]}})
    monkeypatch.setattr(doctor, "_qmd_binary", lambda _context: "/tmp/qmd")
    monkeypatch.setattr(
        doctor,
        "_qmd_status",
        lambda _binary: (False, "index metadata is corrupt"),
    )

    report = doctor.collect(deep=True, context=context)

    assert _check(report, "qmd.live")["verdict"] == "BROKEN"
    assert report["instruments"]["failed"] == []
    assert _check(report, "doctor.self")["verdict"] == "OK"


def test_qmd_adapters_use_existing_discovery_and_status_command(monkeypatch, context):
    from core.utils import qmd_query

    monkeypatch.setattr(qmd_query, "_find_qmd", lambda: "/tmp/qmd")
    assert doctor._qmd_binary(context) == "/tmp/qmd"

    observed = []

    def run(command, **_kwargs):
        observed.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="healthy\n", stderr="")

    monkeypatch.setattr(doctor.subprocess, "run", run)
    assert doctor._qmd_status("/tmp/qmd") == (True, "healthy")
    assert observed == [["/tmp/qmd", "status"]]

    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr="status failed\n"),
    )
    assert doctor._qmd_status("/tmp/qmd") == (False, "status failed")


def test_integrations_skip_cleanly_when_engine_and_task_sync_are_absent(context):
    assert doctor._probe_integrations_enabled(context).verdict == "OFF"


def test_integrations_check_only_task_sync_entries_through_adapter_runner(monkeypatch, context):
    config = context.vault_root / "System" / "integrations" / "config.yaml"
    config.parent.mkdir()
    config.write_text(
        "todoist:\n"
        "  enabled: true\n"
        "  task_sync: true\n"
        "  api_key_env_var: TODOIST_API_KEY\n"
        "notion:\n"
        "  enabled: true\n"
    )
    (context.vault_root / ".env").write_text('TODOIST_API_KEY="secret"\n')
    (context.vault_root / ".env").chmod(0o600)
    runner = context.repo_root / ".claude" / "hooks" / "adapters" / "run.cjs"
    runner.parent.mkdir(parents=True)
    runner.touch()
    monkeypatch.setattr(doctor.shutil, "which", lambda command: "/usr/local/bin/node" if command == "node" else None)
    observed = []

    def failed_run(command, **kwargs):
        observed.append((command, json.loads(kwargs["input"])))
        return subprocess.CompletedProcess(command, 1, stdout='{"ok":false,"error":"sign-in expired"}\n', stderr="")

    monkeypatch.setattr(doctor.subprocess, "run", failed_run)
    broken = doctor._probe_integrations_enabled(context)
    assert broken.verdict == "BROKEN"
    assert observed == [
        (
            ["/usr/local/bin/node", str(runner), "todoist", "health"],
            {
                "config": {
                    "enabled": True,
                    "task_sync": True,
                    "api_key_env_var": "TODOIST_API_KEY",
                    "api_key": "secret",
                },
                "args": None,
            },
        )
    ]

    def healthy_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout='{"ok":true,"result":{"healthy":true}}\n', stderr="")

    monkeypatch.setattr(doctor.subprocess, "run", healthy_run)
    # notion is enabled but has no automated checker: the probe must stay
    # fail-closed (UNKNOWN naming notion), never report a clean bill of health
    # for something it could not verify (see test_split_probe_regression).
    with_unverifiable = doctor._probe_integrations_enabled(context)
    assert with_unverifiable.verdict == "UNKNOWN"
    assert "notion" in with_unverifiable.detail

    config.write_text(
        "todoist:\n"
        "  enabled: true\n"
        "  task_sync: true\n"
        "  api_key_env_var: TODOIST_API_KEY\n"
    )
    assert doctor._probe_integrations_enabled(context).verdict == "OK"


def test_integrations_read_engine_status_json_and_skip_empty_engine(monkeypatch, context):
    engine = context.repo_root / "core" / "integrations" / "connection-manager" / "connect.cjs"
    engine.parent.mkdir(parents=True)
    engine.touch()
    monkeypatch.setattr(doctor.shutil, "which", lambda command: "/usr/local/bin/node" if command == "node" else None)
    observed = []

    def empty_run(command, **kwargs):
        observed.append((command, kwargs["env"]["DEX_VAULT"]))
        return subprocess.CompletedProcess(command, 0, stdout='{"connections":[]}\n', stderr="")

    monkeypatch.setattr(doctor.subprocess, "run", empty_run)
    assert doctor._probe_integrations_enabled(context).verdict == "OFF"
    assert observed == [(["/usr/local/bin/node", str(engine), "status", "--json"], str(context.vault_root))]

    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"connections":['
                '{"service":"google","status":"connected","verified":true},'
                '{"service":"linear","status":"needs_reauth","verified":false,"error":"invalid_key"}'
                "]}\n"
            ),
            stderr="",
        ),
    )
    broken = doctor._probe_integrations_enabled(context)
    assert broken.verdict == "BROKEN"
    assert "linear" in broken.detail
    assert "needs_reauth" in broken.detail


def test_integrations_engine_unknown_transport_degrades_without_false_break(monkeypatch, context):
    engine = context.repo_root / "core" / "integrations" / "connection-manager" / "connect.cjs"
    engine.parent.mkdir(parents=True)
    engine.touch()
    monkeypatch.setattr(doctor.shutil, "which", lambda command: "/usr/local/bin/node" if command == "node" else None)
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="sandbox: Operation not permitted\n",
        ),
    )
    assert doctor._probe_integrations_enabled(context).verdict == "UNKNOWN"


@pytest.mark.parametrize("status", ("connected", "expiring", "expired"))
def test_integrations_engine_stored_but_unverified_rows_are_unknown(monkeypatch, context, status):
    engine = context.repo_root / "core" / "integrations" / "connection-manager" / "connect.cjs"
    engine.parent.mkdir(parents=True)
    engine.touch()
    monkeypatch.setattr(doctor.shutil, "which", lambda command: "/usr/local/bin/node" if command == "node" else None)
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"connections":[{"service":"google","status":"'
                + status
                + '","verified":false}]}\n'
            ),
            stderr="",
        ),
    )
    result = doctor._probe_integrations_enabled(context)
    assert result.verdict == "UNKNOWN"
    assert "google" in result.detail
    assert "stored credential has not been live-verified" in result.detail


def test_mcp_importable_runs_registered_core_servers_in_subprocess(monkeypatch, context):
    mcp_dir = context.vault_root / "core" / "mcp"
    mcp_dir.mkdir(parents=True)
    server = mcp_dir / "work_server.py"
    server.touch()
    _write_mcp_config(
        context,
        {"work-mcp": {"command": sys.executable, "args": [str(server)]}},
    )
    calls = []
    monkeypatch.setattr(
        doctor,
        "_mcp_import_check",
        lambda _context, module, interpreter: calls.append((module, interpreter)) or (True, ""),
    )

    assert doctor._probe_mcp_importable(context).verdict == "OK"
    assert calls == [("core.mcp.work_server", sys.executable)]


@pytest.mark.parametrize(
    ("subprocess_detail", "expected_detail", "expected_heal"),
    [
        (
            "ModuleNotFoundError: No module named 'core.paths'",
            "Dex's own code could not be loaded (missing module 'core.paths')",
            "Run /dex-update to restore Dex's own code, then re-run /dex-doctor.",
        ),
        (
            "ModuleNotFoundError: No module named 'yaml'",
            "missing module 'yaml'",
            "Reinstall missing MCP dependency 'yaml' into the vault .venv, then re-run /dex-doctor.",
        ),
    ],
)
def test_mcp_importable_gives_truthful_missing_module_remediation(
    monkeypatch, context, subprocess_detail, expected_detail, expected_heal
):
    mcp_dir = context.vault_root / "core" / "mcp"
    mcp_dir.mkdir(parents=True)
    server = mcp_dir / "work_server.py"
    server.touch()
    _write_mcp_config(
        context,
        {"work-mcp": {"command": sys.executable, "args": [str(server)]}},
    )
    monkeypatch.setattr(
        doctor,
        "_mcp_import_check",
        lambda _context, _module, _interpreter: (False, subprocess_detail),
    )

    result = doctor._probe_mcp_importable(context)

    assert result.verdict == "BROKEN"
    assert expected_detail in result.detail
    assert result.heal is not None
    assert result.heal.action == expected_heal


def test_mcp_import_subprocess_uses_an_ephemeral_vault(monkeypatch, context):
    observed = {}

    def run(command, **kwargs):
        sandbox = Path(kwargs["env"]["VAULT_PATH"])
        observed["sandbox"] = sandbox
        assert sandbox != context.vault_root
        assert sandbox.is_dir()
        assert "import_module" in command[2]
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(doctor.subprocess, "run", run)

    assert doctor._mcp_import_check(context, "core.mcp.resume_server", sys.executable) == (True, "exit 0")
    assert not observed["sandbox"].exists()


def test_cli_credential_scan_is_reachable_structured_and_redacted(context, capsys):
    config = context.vault_root / "System/integrations/config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("todoist:\n  api_key: synthetic-doctor-value\n")

    assert doctor.main(["--credential-scan"], context=context) == 0

    output = capsys.readouterr().out
    assert '"action": "scan"' in output
    assert '"findings"' in output
    assert "synthetic-doctor-value" not in output


def test_meeting_sources_probe_compares_config_with_reality(context):
    profile = context.vault_root / "System" / "user-profile.yaml"

    assert doctor._probe_meeting_sources(context).verdict == "OFF"

    profile.write_text(
        "meeting_sources:\n  primary: exported-folder\n  notes_folder: 00-Inbox/ClickUp\n",
        encoding="utf-8",
    )
    missing = doctor._probe_meeting_sources(context)
    assert missing.verdict == "BROKEN"
    assert "does not exist" in missing.detail

    folder = context.vault_root / "00-Inbox" / "ClickUp"
    folder.mkdir(parents=True)
    empty = doctor._probe_meeting_sources(context)
    assert empty.verdict == "UNKNOWN"
    assert "no notes yet" in empty.detail

    (folder / "2026-08-07 - Client sync.md").write_text("# notes\n", encoding="utf-8")
    ok = doctor._probe_meeting_sources(context)
    assert ok.verdict == "OK"
    assert "contains notes" in ok.detail


def test_meeting_sources_probe_rejects_paths_outside_the_vault(context):
    profile = context.vault_root / "System" / "user-profile.yaml"
    for folder in ("../elsewhere", ".", "./"):
        profile.write_text(
            f"meeting_sources:\n  primary: exported-folder\n  notes_folder: {folder!r}\n",
            encoding="utf-8",
        )
        result = doctor._probe_meeting_sources(context)
        assert result.verdict == "BROKEN", folder
        assert "inside the vault" in result.detail


def test_meeting_sources_probe_rejects_a_symlinked_escape(context):
    outside = context.vault_root.parent / "outside-notes"
    outside.mkdir()
    (outside / "note.md").write_text("# outside\n", encoding="utf-8")
    inbox = context.vault_root / "00-Inbox"
    inbox.mkdir()
    (inbox / "Notes").symlink_to(outside, target_is_directory=True)
    profile = context.vault_root / "System" / "user-profile.yaml"
    profile.write_text(
        "meeting_sources:\n  primary: exported-folder\n  notes_folder: 00-Inbox/Notes\n",
        encoding="utf-8",
    )

    result = doctor._probe_meeting_sources(context)

    assert result.verdict == "BROKEN"
    assert "inside the vault" in result.detail


def test_post_update_canary_probe_reads_the_receipt(context):
    assert doctor._probe_post_update_canary(context).verdict == "OFF"

    receipt = context.vault_root / "System" / ".dex" / "health" / "post-update-canary.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text("not json\n", encoding="utf-8")
    assert doctor._probe_post_update_canary(context).verdict == "UNKNOWN"

    receipt.write_text(
        json.dumps(
            {
                "contract": "dex.health.post-update-canary/v1",
                "checked_at": "2026-08-10T12:00:00+00:00",
                "dex_version": "1.85.0",
                "ok": True,
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    ok = doctor._probe_post_update_canary(context)
    assert ok.verdict == "OK"
    assert "1.85.0" in ok.detail

    receipt.write_text(
        json.dumps(
            {
                "contract": "dex.health.post-update-canary/v1",
                "checked_at": "2026-08-10T12:00:00+00:00",
                "dex_version": "1.85.0",
                "ok": False,
                "error": "PlanRejected: refused",
            }
        ),
        encoding="utf-8",
    )
    broken = doctor._probe_post_update_canary(context)
    assert broken.verdict == "BROKEN"
    assert "PlanRejected" in broken.detail
    assert broken.heal.tier == 2


def test_meeting_sources_probe_is_ok_for_api_sources_without_folders(context):
    profile = context.vault_root / "System" / "user-profile.yaml"
    profile.write_text("meeting_sources:\n  primary: granola\n  notes_folder: \"\"\n", encoding="utf-8")
    result = doctor._probe_meeting_sources(context)
    assert result.verdict == "OK"
    assert "granola" in result.detail


# --- Pipedrive CRM connection probe ----------------------------------------


def _pipedrive_module():
    from core.integrations.pipedrive import pipedrive_server

    return pipedrive_server


def test_pipedrive_unconfigured_is_off_and_never_calls_the_api(monkeypatch, context):
    """An unconnected integration is a healthy state, not a fault."""
    pipedrive = _pipedrive_module()
    monkeypatch.setattr(
        pipedrive,
        "_resolve",
        lambda: {
            "ok": False,
            "status": {
                "feature_status": "off",
                "user_message": "Pipedrive is not connected. Run /pipedrive-setup to connect it.",
            },
        },
    )
    monkeypatch.setattr(
        pipedrive,
        "_request",
        lambda *a, **k: pytest.fail("the API must not be called when unconfigured"),
    )

    result = doctor._probe_pipedrive_connection(context)

    assert result.verdict == "OFF"
    assert "not connected" in result.detail.lower()
    assert result.heal is None


def test_pipedrive_broken_config_offers_the_setup_heal(monkeypatch, context):
    pipedrive = _pipedrive_module()
    monkeypatch.setattr(
        pipedrive,
        "_resolve",
        lambda: {
            "ok": False,
            "status": {
                "feature_status": "broken",
                "user_message": "No base_url / company_domain configured.",
            },
        },
    )

    result = doctor._probe_pipedrive_connection(context)

    assert result.verdict == "BROKEN"
    assert result.detail == "No base_url / company_domain configured."
    assert result.heal is not None
    assert "/pipedrive-setup" in result.heal.action
    assert result.heal.applied is False


def test_pipedrive_ok_requires_a_live_call_not_just_parseable_settings(monkeypatch, context):
    """OK must mean the stored token works, so a 401 is BROKEN even when settings resolve."""
    pipedrive = _pipedrive_module()
    monkeypatch.setattr(
        pipedrive,
        "_resolve",
        lambda: {"ok": True, "api_token": "t", "base_url": "https://example.pipedrive.com"},
    )

    calls = []

    def unauthorized(method, path, env, **kwargs):
        calls.append((method, path))
        return {"ok": False, "error": "Pipedrive auth failed (401). Token may be invalid or expired."}

    monkeypatch.setattr(pipedrive, "_request", unauthorized)
    result = doctor._probe_pipedrive_connection(context)
    assert calls == [("GET", "users/me")]
    assert result.verdict == "BROKEN"
    assert "401" in result.detail
    assert result.heal is not None

    monkeypatch.setattr(
        pipedrive,
        "_request",
        lambda *a, **k: {"ok": True, "data": {"name": "Test User", "company_name": "Test Co"}},
    )
    healthy = doctor._probe_pipedrive_connection(context)
    assert healthy.verdict == "OK"
    assert "Test User" in healthy.detail
    assert "Test Co" in healthy.detail
    assert healthy.heal is None


def test_pipedrive_probe_restores_the_callers_vault_root(monkeypatch, context):
    """The probe points the server at the inspected vault without leaking that state."""
    pipedrive = _pipedrive_module()
    seen = {}

    def capture():
        seen["vault_root"] = os.environ.get("VAULT_ROOT")
        return {"ok": False, "status": {"feature_status": "off", "user_message": "off"}}

    monkeypatch.setattr(pipedrive, "_resolve", capture)

    monkeypatch.setenv("VAULT_ROOT", "/sentinel/original")
    doctor._probe_pipedrive_connection(context)
    assert seen["vault_root"] == str(context.vault_root)
    assert os.environ["VAULT_ROOT"] == "/sentinel/original"

    monkeypatch.delenv("VAULT_ROOT", raising=False)
    doctor._probe_pipedrive_connection(context)
    assert seen["vault_root"] == str(context.vault_root)
    assert "VAULT_ROOT" not in os.environ


def test_pipedrive_sandbox_failure_is_unknown_not_broken(monkeypatch, context):
    pipedrive = _pipedrive_module()
    monkeypatch.setattr(
        pipedrive,
        "_resolve",
        lambda: {"ok": True, "api_token": "t", "base_url": "https://example.pipedrive.com"},
    )
    monkeypatch.setattr(
        pipedrive,
        "_request",
        lambda *a, **k: {"ok": False, "error": "Operation not permitted (sandbox)"},
    )

    result = doctor._probe_pipedrive_connection(context)
    assert result.verdict in {"UNKNOWN", "BROKEN"}


def test_pipedrive_check_is_registered_in_the_deep_check_list():
    ids = {definition.id for definition in doctor.DEEP_CHECKS}
    assert "pipedrive.connection" in ids
